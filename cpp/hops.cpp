#include <iostream>
#include <algorithm>
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
#include "utils.hpp"
using namespace std;

struct Options {
    int no_of_runs = 1000;
    string src_node = "";
    string tgt_node = "";
    string rw_variant = "LRV";
    string edges_csv = "";
    bool record_paths = false;
    bool erase_loops = false;
};

struct HopStats {
    int min_hops, max_hops;
    double mean_hops;
    int q1_hops, q2_hops, q3_hops;
    double max_hit_prob;
    string max_hit_node;
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
    const Graph &graph,
    int src_idx,
    int tgt_idx,
    int no_of_runs
);
filesystem::path cache_dir_from_argv0(const char *argv0);
string cache_key_for_run(const Options &opts, const Graph &graph, const vector<vector<int>> &adj);
bool try_print_cached_output(const filesystem::path &cache_file);
void write_cache_output(const filesystem::path &cache_file, const string &output);
vector<int> erase_loops_from_history(const vector<int> &history);

int main(int argc, char **argv) {
    Options opts = parse_args(argc, argv);
    Graph graph = opts.edges_csv.empty() ? Graph(cin) : Graph(opts.edges_csv);
    const auto &adj = graph.adj_list();

    int src_idx = graph.node_index(opts.src_node);
    int tgt_idx = graph.node_index(opts.tgt_node);
    filesystem::path cache_dir = cache_dir_from_argv0(argv[0]);
    string cache_key = cache_key_for_run(opts, graph, adj);
    filesystem::path cache_file = cache_dir / (cache_key + ".txt");
    if (try_print_cached_output(cache_file)) {
        return 0;
    }

    const int node_count = static_cast<int>(adj.size());
    vector<int> hop_counts(opts.no_of_runs, 0);
    vector<int> hit_count(node_count, 0);
    const bool keep_history = opts.record_paths || opts.erase_loops;
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
    vector<thread> workers;
    workers.reserve(thread_count);

    auto run_chunk = [&](int tid, int start_run, int end_run) -> void {
        vector<int> &local_hits = local_hit_counts[tid];
        for (int i = start_run; i < end_run; i++) {
            unique_ptr<RwToken> token = make_token(i);
            int position = src_idx;
            int hops = 0;
            set<int> seen_nodes = {position};
            vector<int> history;
            if (keep_history) {
                history.push_back(position);
            }
            while (position != tgt_idx) {
                int next = token->choose_next_and_update(position, adj[position]);
                position = next;
                seen_nodes.insert(position);
                if (keep_history) {
                    history.push_back(position);
                }
                hops++;
                if (hops > 100000) {
                    throw runtime_error("Random walk exceeded 100000 steps");
                }
            }
            if (opts.erase_loops) {
                history = erase_loops_from_history(history);
                hops = static_cast<int>(history.size()) - 1;
                seen_nodes = set<int>(history.begin(), history.end());
            }
            hop_counts[i] = hops;
            for (int node : seen_nodes) {
                local_hits[node]++;
            }
            if (opts.record_paths) {
                vector<string> path_names;
                path_names.reserve(history.size());
                for (int node : history) {
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
        }
    }

    HopStats stats = compute_stats(hop_counts, hit_count, graph, src_idx, tgt_idx, opts.no_of_runs);
    if (opts.record_paths) {
        stats.paths = std::move(recorded_paths);
    }
    ostringstream out;
    stats.print(out, opts);
    string output = out.str();
    cout << output;
    write_cache_output(cache_file, output);
    return 0;
}

void print_usage(const char *prog_name) {
    cerr << "Usage: " << prog_name
         << " (--src-node|-s) <node> (--tgt-node|-t) <node> "
            "[(--no-of-runs|-n) <int>] [(--rw-variant|-w) <name>] "
           "[(--edges-csv|-e) <path>] [--record-paths] [--erase-loops]" << endl;
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

    int max_hit_count = 0;
    int max_hit_node = -1;
    for (int node = 0; node < static_cast<int>(hit_count.size()); node++) {
        int count = hit_count[node];
        if (node == src_idx || node == tgt_idx) continue;
        if (count > max_hit_count) {
            max_hit_count = count;
            max_hit_node = node;
        }
    }

    HopStats stats;
    stats.min_hops = min_hops;
    stats.max_hops = max_hops;
    stats.mean_hops = mean_hops;
    stats.q1_hops = q1_hops;
    stats.q2_hops = q2_hops;
    stats.q3_hops = q3_hops;
    stats.max_hit_prob = static_cast<double>(max_hit_count) / no_of_runs;
    stats.max_hit_node = max_hit_node == -1 ? "N/A" : graph.node_name(max_hit_node);
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

string cache_key_for_run(const Options &opts, const Graph &graph, const vector<vector<int>> &adj) {
    ostringstream fingerprint;
    fingerprint << "hops-cache-v2";
    fingerprint << "|runs=" << opts.no_of_runs;
    fingerprint << "|src=" << opts.src_node;
    fingerprint << "|tgt=" << opts.tgt_node;
    fingerprint << "|variant=" << opts.rw_variant;
    fingerprint << "|record_paths=" << (opts.record_paths ? 1 : 0);
    fingerprint << "|erase_loops=" << (opts.erase_loops ? 1 : 0);

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

bool try_print_cached_output(const filesystem::path &cache_file) {
    if (!filesystem::exists(cache_file)) {
        return false;
    }
    ifstream in(cache_file);
    if (!in.is_open()) {
        return false;
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
