#include <iostream>
#include <algorithm>
#include <cctype>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <memory>
#include <numeric>
#include <sstream>
#include <thread>
#include <unordered_map>
#include <vector>
#include <string_view>
#include <set>
#include "graph.hpp"
#include "walk.hpp"
using namespace std;

const string REUSABLE_CACHE_MAGIC = "RWKR_HOPS_REUSABLE_CACHE_V1";

struct Options {
    int no_of_runs = 1000;
    string src_node = "";
    string tgt_node = "";
    string rw_variant = "LRV";
    string edges_csv = "";
    vector<string> cartel_nodes;
    bool record_paths = false;
    bool erase_loops = false;
};

struct HopStats {
    int min_hops, max_hops;
    double mean_hops;
    int q1_hops, q2_hops, q3_hops;
    double max_hit_prob;
    string max_hit_node;
    double max_hit_prob_lerw;
    string max_hit_node_lerw;
    double cartel_hit_prob_lerw = 0.0;
    vector<vector<string>> paths;

    void print(ostream &out, Options opts) const {
        out << "context: " << opts.src_node << " -> " << opts.tgt_node << " (" << opts.rw_variant << ", "<< opts.no_of_runs<< " runs)" << endl;
        out << "min_hops: " << min_hops << endl;
        out << "max_hops: " << max_hops << endl;
        out << "mean_hops: " << mean_hops << endl;
        out << "q1_hops: " << q1_hops << endl;
        out << "q2_hops: " << q2_hops << endl;
        out << "q3_hops: " << q3_hops << endl;
        out << "max_hit_prob: " << max_hit_prob << endl;
        out << "max_hit_node: " << max_hit_node << endl;
        out << "max_hit_prob_lerw: " << max_hit_prob_lerw << endl;
        out << "max_hit_node_lerw: " << max_hit_node_lerw << endl;
        if(!opts.cartel_nodes.empty()){
            out << "cartel_nodes:";
            for(const string &node : opts.cartel_nodes){
                out << " " << node;
            }
            out << endl;
            out << "cartel_hit_prob_lerw: " << cartel_hit_prob_lerw << endl;
        }
        if(opts.record_paths){
            out << "path_count: " << paths.size() << endl;
            for(size_t i = 0; i < paths.size(); i++){
                string zero_padded_i = to_string(i);
                while(zero_padded_i.size()<to_string(paths.size()-1).size())
                    zero_padded_i = "0" + zero_padded_i;
                out << "path "<<zero_padded_i<<":";
                for(const string &node : paths[i]){
                    out << " " << node;
                }
                out << endl;
            }
        }
    }
};

Options parse_args(int argc, char **argv);
void print_usage(const char *prog_name);
HopStats compute_stats(
    const vector<int> &hop_counts,
    const vector<int> &hit_count,
    const vector<int> &hit_count_lerw,
    const Graph &graph,
    int src_idx,
    int tgt_idx,
    int no_of_runs
);
filesystem::path cache_dir_from_argv0(const char *argv0);
bool uses_reusable_cartel_cache(const Options &opts);
string cache_key_for_run(const Options &opts, const Graph &graph, const vector<vector<int>> &adj, bool reusable_cartel_cache);
bool try_print_cached_output(const filesystem::path &cache_file, const Options &opts, const Graph &graph);
void write_cache_output(const filesystem::path &cache_file, const string &output);
void write_reusable_cache_output(
    const filesystem::path &cache_file,
    const string &base_output,
    const Graph &graph,
    const vector<int> &hit_count_lerw,
    const vector<vector<int>> &cohit_count_lerw
);
bool read_reusable_cache_output(
    const filesystem::path &cache_file,
    const Graph &graph,
    string &base_output,
    vector<int> &hit_count_lerw,
    vector<vector<int>> &cohit_count_lerw
);
vector<int> erase_loops_from_history(const vector<int> &history);
vector<string> parse_node_list(const string &node_list);
string trim_copy(string s);
double cartel_hit_probability_lerw(
    const Options &opts,
    const Graph &graph,
    const vector<int> &hit_count_lerw,
    const vector<vector<int>> &cohit_count_lerw
);
void print_cartel_result(ostream &out, const Options &opts, double cartel_hit_prob_lerw);

int main(int argc, char **argv) {
    Options opts = parse_args(argc, argv);
    Graph graph = opts.edges_csv.empty() ? Graph(cin) : Graph(opts.edges_csv);
    const auto &adj = graph.adj_list();

    int src_idx = graph.node_index(opts.src_node);
    int tgt_idx = graph.node_index(opts.tgt_node);
    const int node_count = static_cast<int>(adj.size());
    vector<char> is_cartel_node(node_count, 0);
    for (const string &node_name : opts.cartel_nodes) {
        is_cartel_node[graph.node_index(node_name)] = 1;
    }
    filesystem::path cache_dir = cache_dir_from_argv0(argv[0]);
    bool reusable_cartel_cache = uses_reusable_cartel_cache(opts);
    string cache_key = cache_key_for_run(opts, graph, adj, reusable_cartel_cache);
    filesystem::path cache_file = cache_dir / (cache_key + ".txt");
    if (try_print_cached_output(cache_file, opts, graph)) {
        return 0;
    }

    vector<int> hop_counts(opts.no_of_runs, 0);
    vector<int> hit_count(node_count, 0);
    vector<int> hit_count_lerw(node_count, 0);
    vector<vector<int>> cohit_count_lerw(node_count, vector<int>(node_count, 0));
    vector<vector<string>> recorded_paths;
    if (opts.record_paths) {
        recorded_paths.resize(opts.no_of_runs);
    }

    auto make_token = [&](int seed) -> unique_ptr<RwToken> {
        if (opts.rw_variant == "R") return make_unique<RToken>(src_idx, tgt_idx, seed);
        if (opts.rw_variant == "NB") return make_unique<NbToken>(src_idx, tgt_idx, seed);
        if (opts.rw_variant == "LRV") return make_unique<LrvToken>(src_idx, tgt_idx, seed);
        if (opts.rw_variant == "NC") return make_unique<NcToken>(src_idx, tgt_idx, seed, node_count);
        if (opts.rw_variant == "HS") return make_unique<HsToken>(src_idx, tgt_idx, seed);
        return nullptr;
    };
    if (!make_token(0)) {
        cerr << "Unknown random walk variant: " << opts.rw_variant << endl;
        return 1;
    }

    unsigned int hw_threads = thread::hardware_concurrency();
    int thread_count = static_cast<int>(hw_threads == 0 ? 1 : hw_threads);
    thread_count = min(thread_count, opts.no_of_runs);
    vector<vector<int>> local_hit_counts(thread_count, vector<int>(node_count, 0));
    vector<vector<int>> local_hit_counts_lerw(thread_count, vector<int>(node_count, 0));
    vector<vector<vector<int>>> local_cohit_counts_lerw(
        thread_count,
        vector<vector<int>>(node_count, vector<int>(node_count, 0))
    );
    vector<int> local_cartel_hit_counts(thread_count, 0);
    vector<thread> workers;
    workers.reserve(thread_count);

    auto run_chunk = [&](int tid, int start_run, int end_run) -> void {
        vector<int> &local_hits = local_hit_counts[tid];
        vector<int> &local_hits_lerw = local_hit_counts_lerw[tid];
        vector<vector<int>> &local_cohits_lerw = local_cohit_counts_lerw[tid];
        for (int i = start_run; i < end_run; i++) {
            unique_ptr<RwToken> token = make_token(i);
            int position = src_idx;
            int hops_raw = 0;
            set<int> seen_nodes_raw = {position};
            vector<int> history;
            history.push_back(position);
            while (position != tgt_idx) {
                int next = token->choose_next_and_update(position, adj[position]);
                position = next;
                seen_nodes_raw.insert(position);
                history.push_back(position);
                hops_raw++;
                if (hops_raw > 100000) {
                    throw runtime_error("Random walk exceeded 100000 steps");
                }
            }

            // Loop-erasure post-processing (LERW).
            vector<int> history_lerw = erase_loops_from_history(history);
            set<int> seen_nodes_lerw(history_lerw.begin(), history_lerw.end());
            vector<int> seen_nodes_lerw_list(seen_nodes_lerw.begin(), seen_nodes_lerw.end());

            int hops_effective = opts.erase_loops ? static_cast<int>(history_lerw.size()) - 1 : hops_raw;
            hop_counts[i] = hops_effective;

            // Hits for the raw walk (always), independent of --erase-loops.
            for (int node : seen_nodes_raw) {
                local_hits[node]++;
            }

            // Hits for the loop-erased walk always.
            for (int node : seen_nodes_lerw) {
                local_hits_lerw[node]++;
            }
            for (size_t a = 0; a < seen_nodes_lerw_list.size(); a++) {
                for (size_t b = a + 1; b < seen_nodes_lerw_list.size(); b++) {
                    local_cohits_lerw[seen_nodes_lerw_list[a]][seen_nodes_lerw_list[b]]++;
                }
            }
            if (!opts.cartel_nodes.empty()) {
                for (int node : seen_nodes_lerw) {
                    if (is_cartel_node[node]) {
                        local_cartel_hit_counts[tid]++;
                        break;
                    }
                }
            }
            if (opts.record_paths) {
                vector<string> path_names;
                const vector<int> &history_to_record = opts.erase_loops ? history_lerw : history;
                path_names.reserve(history_to_record.size());
                for (int node : history_to_record) {
                    path_names.push_back(graph.node_name(node));
                }
                recorded_paths[i] = std::move(path_names);
            }
        }
    };

    int base_runs = opts.no_of_runs / thread_count;
    int extra_runs = opts.no_of_runs % thread_count;
    int next_start = 0;
    for (int tid = 0; tid < thread_count; tid++) {
        int chunk_size = base_runs + (tid < extra_runs ? 1 : 0);
        int start_run = next_start;
        int end_run = start_run + chunk_size;
        workers.emplace_back(run_chunk, tid, start_run, end_run);
        next_start = end_run;
    }
    for (thread &worker : workers) {
        worker.join();
    }

    for (int tid = 0; tid < thread_count; tid++) {
        for (int node = 0; node < node_count; node++) {
            hit_count[node] += local_hit_counts[tid][node];
            hit_count_lerw[node] += local_hit_counts_lerw[tid][node];
            for (int other = node + 1; other < node_count; other++) {
                cohit_count_lerw[node][other] += local_cohit_counts_lerw[tid][node][other];
            }
        }
    }
    int cartel_hit_count_lerw = accumulate(
        local_cartel_hit_counts.begin(),
        local_cartel_hit_counts.end(),
        0
    );

    HopStats stats = compute_stats(
        hop_counts,
        hit_count,
        hit_count_lerw,
        graph,
        src_idx,
        tgt_idx,
        opts.no_of_runs
    );
    if (!opts.cartel_nodes.empty()) {
        if (opts.cartel_nodes.size() <= 2) {
            stats.cartel_hit_prob_lerw = cartel_hit_probability_lerw(
                opts,
                graph,
                hit_count_lerw,
                cohit_count_lerw
            );
        } else {
            stats.cartel_hit_prob_lerw = static_cast<double>(cartel_hit_count_lerw) / opts.no_of_runs;
        }
    }
    if (opts.record_paths) {
        stats.paths = std::move(recorded_paths);
    }
    ostringstream out;
    if (reusable_cartel_cache) {
        Options base_opts = opts;
        base_opts.cartel_nodes.clear();
        stats.print(out, base_opts);
        if (!opts.cartel_nodes.empty()) {
            print_cartel_result(out, opts, stats.cartel_hit_prob_lerw);
        }
    } else {
        stats.print(out, opts);
    }
    string output = out.str();
    cout << output;
    if (reusable_cartel_cache) {
        ostringstream base_out;
        Options base_opts = opts;
        base_opts.cartel_nodes.clear();
        stats.print(base_out, base_opts);
        write_reusable_cache_output(
            cache_file,
            base_out.str(),
            graph,
            hit_count_lerw,
            cohit_count_lerw
        );
    } else {
        write_cache_output(cache_file, output);
    }
    return 0;
}

void print_usage(const char *prog_name) {
    cerr << "Usage: " << prog_name
         << " (--src-node|-s) <node> (--tgt-node|-t) <node> "
            "[(--no-of-runs|-n) <int>] [(--rw-variant|-w) <name>] "
           "[(--edges-csv|-e) <path>] [--record-paths] [--erase-loops] "
           "[(--cartel|--cartel-nodes) <node[,node...]>]" << endl;
}

Options parse_args(int argc, char **argv){
    Options opts;
    auto fail = [&](const string &msg) -> void {
        cerr << msg << endl;
        print_usage(argv[0]);
        exit(1);
    };

    auto require_value = [&](int &i, string_view flag, bool has_inline, string_view inline_value) -> string {
        if (has_inline) {
            if (inline_value.empty()) {
                fail("Missing value for " + string(flag));
            }
            return string(inline_value);
        }
        if (i + 1 >= argc) {
            fail("Missing value for " + string(flag));
        }
        return argv[++i];
    };

    for(int i=1;i<argc;i++){
        string_view arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            print_usage(argv[0]);
            exit(0);
        }

        size_t eq_pos = arg.find('=');
        bool has_inline = eq_pos != string_view::npos;
        string_view flag = has_inline ? arg.substr(0, eq_pos) : arg;
        string_view inline_value = has_inline ? arg.substr(eq_pos + 1) : string_view{};

        if(flag == "--no-of-runs" || flag == "-n"){
            opts.no_of_runs = stoi(require_value(i, flag, has_inline, inline_value));
        }
        else if(flag == "--src-node" || flag == "-s"){
            opts.src_node = require_value(i, flag, has_inline, inline_value);
        }
        else if(flag == "--tgt-node" || flag == "-t"){
            opts.tgt_node = require_value(i, flag, has_inline, inline_value);
        }
        else if(flag == "--rw-variant" || flag == "-w"){
            opts.rw_variant = require_value(i, flag, has_inline, inline_value);
        }
        else if(flag == "--edges-csv" || flag == "-e"){
            opts.edges_csv = require_value(i, flag, has_inline, inline_value);
        }
        else if(flag == "--cartel" || flag == "--cartel-nodes"){
            opts.cartel_nodes = parse_node_list(require_value(i, flag, has_inline, inline_value));
            if (opts.cartel_nodes.empty()) {
                fail("Cartel must contain at least one node");
            }
        }
        else if(flag == "--record-paths"){
            opts.record_paths = true;
        }
        else if(flag == "--erase-loops"){
            opts.erase_loops = true;
        }
        else{
            fail("Unknown argument: " + string(arg));
        }
    }
    if(opts.src_node.empty() || opts.tgt_node.empty()){
        fail("Source and target nodes are required");
    }
    if (opts.no_of_runs <= 0) {
        fail("--no-of-runs must be > 0");
    }
    return opts;
}

HopStats compute_stats(
    const vector<int> &hop_counts,
    const vector<int> &hit_count,
    const vector<int> &hit_count_lerw,
    const Graph &graph,
    int src_idx,
    int tgt_idx,
    int no_of_runs
) {
    auto percentile_value = [](const vector<int> &sorted_values, double p) -> int {
        int idx = static_cast<int>((sorted_values.size() - 1) * p);
        return sorted_values[idx];
    };

    vector<int> sorted_hops = hop_counts;
    sort(sorted_hops.begin(), sorted_hops.end());

    int min_hops = sorted_hops.front();
    int max_hops = sorted_hops.back();
    double mean_hops = static_cast<double>(accumulate(hop_counts.begin(), hop_counts.end(), 0LL)) / no_of_runs;
    int q1_hops = percentile_value(sorted_hops, 0.25);
    int q2_hops = percentile_value(sorted_hops, 0.50);
    int q3_hops = percentile_value(sorted_hops, 0.75);

    auto max_hit = [&](const vector<int> &counts) -> pair<int, int> {
        int best_count = 0;
        int best_node = -1;
        for (int node = 0; node < static_cast<int>(counts.size()); node++) {
            int count = counts[node];
            if (node == src_idx || node == tgt_idx) continue;
            if (count > best_count) {
                best_count = count;
                best_node = node;
            }
        }
        return {best_node, best_count};
    };

    auto [max_hit_node_eff, max_hit_count_eff] = max_hit(hit_count);
    auto [max_hit_node_lerw, max_hit_count_lerw] = max_hit(hit_count_lerw);

    HopStats stats;
    stats.min_hops = min_hops;
    stats.max_hops = max_hops;
    stats.mean_hops = mean_hops;
    stats.q1_hops = q1_hops;
    stats.q2_hops = q2_hops;
    stats.q3_hops = q3_hops;
    stats.max_hit_prob = static_cast<double>(max_hit_count_eff) / no_of_runs;
    stats.max_hit_node = max_hit_node_eff == -1 ? "N/A" : graph.node_name(max_hit_node_eff);
    stats.max_hit_prob_lerw = static_cast<double>(max_hit_count_lerw) / no_of_runs;
    stats.max_hit_node_lerw = max_hit_node_lerw == -1 ? "N/A" : graph.node_name(max_hit_node_lerw);
    return stats;
}

filesystem::path cache_dir_from_argv0(const char *argv0) {
    (void)argv0;

    if (const char *cache_dir = getenv("RWKR_CACHE_DIR"); cache_dir != nullptr && cache_dir[0] != '\0') {
        return filesystem::path(cache_dir);
    }

    error_code ec;
    filesystem::path temp_dir = filesystem::temp_directory_path(ec);
    if (!ec && !temp_dir.empty()) {
        return temp_dir / "random-walk-key-relaying-cache";
    }
    return filesystem::path("/tmp/random-walk-key-relaying-cache");
}

bool uses_reusable_cartel_cache(const Options &opts) {
    return !opts.record_paths && opts.cartel_nodes.size() <= 2;
}

string cache_key_for_run(const Options &opts, const Graph &graph, const vector<vector<int>> &adj, bool reusable_cartel_cache) {
    ostringstream fingerprint;
    fingerprint << "hops-cache-v5";
    fingerprint << "|runs=" << opts.no_of_runs;
    fingerprint << "|src=" << opts.src_node;
    fingerprint << "|tgt=" << opts.tgt_node;
    fingerprint << "|variant=" << opts.rw_variant;
    fingerprint << "|record_paths=" << (opts.record_paths ? 1 : 0);
    fingerprint << "|erase_loops=" << (opts.erase_loops ? 1 : 0);
    fingerprint << "|reusable_cartel_cache=" << (reusable_cartel_cache ? 1 : 0);
    if (!reusable_cartel_cache) {
        fingerprint << "|cartel_nodes=";
        for (const string &node : opts.cartel_nodes) {
            fingerprint << node << ",";
        }
    }

    vector<string> canonical_edges;
    for (int u = 0; u < static_cast<int>(adj.size()); u++) {
        string u_name = graph.node_name(u);
        for (int v : adj[u]) {
            if (u > v) continue;
            string v_name = graph.node_name(v);
            if (v_name < u_name) {
                canonical_edges.push_back(v_name + "|" + u_name);
            } else {
                canonical_edges.push_back(u_name + "|" + v_name);
            }
        }
    }
    sort(canonical_edges.begin(), canonical_edges.end());
    fingerprint << "|edge_count=" << canonical_edges.size();
    for (const string &edge : canonical_edges) {
        fingerprint << "|e=" << edge;
    }
    size_t key = hash<string>{}(fingerprint.str());
    return to_string(key);
}

vector<string> parse_node_list(const string &node_list) {
    stringstream ss(node_list);
    string node;
    set<string> seen;
    while (getline(ss, node, ',')) {
        node = trim_copy(node);
        if (node.empty()) continue;
        seen.insert(node);
    }
    return vector<string>(seen.begin(), seen.end());
}

string trim_copy(string s) {
    while (!s.empty() && isspace(static_cast<unsigned char>(s.back()))) s.pop_back();
    size_t start = 0;
    while (start < s.size() && isspace(static_cast<unsigned char>(s[start]))) start++;
    return s.substr(start);
}

bool try_print_cached_output(const filesystem::path &cache_file, const Options &opts, const Graph &graph) {
    if (!filesystem::exists(cache_file)) {
        return false;
    }
    ifstream in(cache_file);
    if (!in.is_open()) {
        return false;
    }
    if (uses_reusable_cartel_cache(opts)) {
        in.close();
        string base_output;
        vector<int> hit_count_lerw;
        vector<vector<int>> cohit_count_lerw;
        if (!read_reusable_cache_output(
                cache_file,
                graph,
                base_output,
                hit_count_lerw,
                cohit_count_lerw
            )) {
            return false;
        }
        cout << base_output;
        if (!opts.cartel_nodes.empty()) {
            double cartel_hit_prob = cartel_hit_probability_lerw(
                opts,
                graph,
                hit_count_lerw,
                cohit_count_lerw
            );
            print_cartel_result(cout, opts, cartel_hit_prob);
        }
        return true;
    }
    cout << in.rdbuf();
    return true;
}

void write_cache_output(const filesystem::path &cache_file, const string &output) {
    error_code ec;
    filesystem::create_directories(cache_file.parent_path(), ec);
    ofstream out(cache_file);
    if (!out.is_open()) {
        return;
    }
    out << output;
}

void write_reusable_cache_output(
    const filesystem::path &cache_file,
    const string &base_output,
    const Graph &graph,
    const vector<int> &hit_count_lerw,
    const vector<vector<int>> &cohit_count_lerw
) {
    error_code ec;
    filesystem::create_directories(cache_file.parent_path(), ec);
    ofstream out(cache_file);
    if (!out.is_open()) {
        return;
    }

    out << REUSABLE_CACHE_MAGIC << endl;
    out << "BEGIN_OUTPUT" << endl;
    out << base_output;
    out << "END_OUTPUT" << endl;
    out << "BEGIN_HIT_LERW" << endl;
    for (int node = 0; node < static_cast<int>(hit_count_lerw.size()); node++) {
        out << node << " " << hit_count_lerw[node] << " " << graph.node_name(node) << endl;
    }
    out << "END_HIT_LERW" << endl;
    out << "BEGIN_COHIT_LERW" << endl;
    for (int u = 0; u < static_cast<int>(cohit_count_lerw.size()); u++) {
        for (int v = u + 1; v < static_cast<int>(cohit_count_lerw[u].size()); v++) {
            if (cohit_count_lerw[u][v] == 0) continue;
            out << u << " " << v << " " << cohit_count_lerw[u][v]
                << " " << graph.node_name(u) << " " << graph.node_name(v) << endl;
        }
    }
    out << "END_COHIT_LERW" << endl;
}

bool read_reusable_cache_output(
    const filesystem::path &cache_file,
    const Graph &graph,
    string &base_output,
    vector<int> &hit_count_lerw,
    vector<vector<int>> &cohit_count_lerw
) {
    ifstream in(cache_file);
    if (!in.is_open()) {
        return false;
    }

    string line;
    if (!getline(in, line) || line != REUSABLE_CACHE_MAGIC) {
        return false;
    }
    if (!getline(in, line) || line != "BEGIN_OUTPUT") {
        return false;
    }

    ostringstream output;
    while (getline(in, line)) {
        if (line == "END_OUTPUT") break;
        output << line << endl;
    }
    if (!in || line != "END_OUTPUT") {
        return false;
    }

    const int node_count = static_cast<int>(graph.adj_list().size());
    hit_count_lerw.assign(node_count, 0);
    cohit_count_lerw.assign(node_count, vector<int>(node_count, 0));

    if (!getline(in, line) || line != "BEGIN_HIT_LERW") {
        return false;
    }
    while (getline(in, line)) {
        if (line == "END_HIT_LERW") break;
        stringstream ss(line);
        int node = -1;
        int count = 0;
        if (!(ss >> node >> count)) {
            return false;
        }
        if (node < 0 || node >= node_count) {
            return false;
        }
        hit_count_lerw[node] = count;
    }
    if (!in || line != "END_HIT_LERW") {
        return false;
    }

    if (!getline(in, line) || line != "BEGIN_COHIT_LERW") {
        return false;
    }
    while (getline(in, line)) {
        if (line == "END_COHIT_LERW") break;
        stringstream ss(line);
        int u = -1;
        int v = -1;
        int count = 0;
        if (!(ss >> u >> v >> count)) {
            return false;
        }
        if (u < 0 || u >= node_count || v < 0 || v >= node_count || u == v) {
            return false;
        }
        if (u > v) swap(u, v);
        cohit_count_lerw[u][v] = count;
    }
    if (!in || line != "END_COHIT_LERW") {
        return false;
    }

    base_output = output.str();
    return true;
}

double cartel_hit_probability_lerw(
    const Options &opts,
    const Graph &graph,
    const vector<int> &hit_count_lerw,
    const vector<vector<int>> &cohit_count_lerw
) {
    if (opts.cartel_nodes.empty()) {
        return 0.0;
    }

    int first = graph.node_index(opts.cartel_nodes[0]);
    if (opts.cartel_nodes.size() == 1) {
        return static_cast<double>(hit_count_lerw[first]) / opts.no_of_runs;
    }

    int second = graph.node_index(opts.cartel_nodes[1]);
    int u = min(first, second);
    int v = max(first, second);
    int union_hit_count = hit_count_lerw[first] + hit_count_lerw[second] - cohit_count_lerw[u][v];
    return static_cast<double>(union_hit_count) / opts.no_of_runs;
}

void print_cartel_result(ostream &out, const Options &opts, double cartel_hit_prob_lerw) {
    out << "cartel_nodes:";
    for (const string &node : opts.cartel_nodes) {
        out << " " << node;
    }
    out << endl;
    out << "cartel_hit_prob_lerw: " << cartel_hit_prob_lerw << endl;
}

vector<int> erase_loops_from_history(const vector<int> &history) {
    vector<int> loop_erased_history;
    loop_erased_history.reserve(history.size());
    unordered_map<int, size_t> first_pos;
    for (int node : history) {
        auto it = first_pos.find(node);
        if (it == first_pos.end()) {
            first_pos[node] = loop_erased_history.size();
            loop_erased_history.push_back(node);
            continue;
        }

        size_t keep_until = it->second;
        for (size_t idx = keep_until + 1; idx < loop_erased_history.size(); idx++) {
            first_pos.erase(loop_erased_history[idx]);
        }
        loop_erased_history.resize(keep_until + 1);
    }
    return loop_erased_history;
}
