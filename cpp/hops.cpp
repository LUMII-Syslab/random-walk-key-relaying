#include <iostream>
#include <algorithm>
#include <memory>
#include <numeric>
#include <thread>
#include <vector>
#include <string_view>
#include <set>
#include "walk.hpp"
#include "utils.hpp"
using namespace std;

struct Options {
    int no_of_runs = 1000;
    string src_node = "";
    string tgt_node = "";
    string rw_variant = "LRV";
    string edges_csv = "";
};

struct HopStats {
    int min_hops, max_hops;
    double mean_hops;
    int q1_hops, q2_hops, q3_hops;
    double max_hit_prob;
    string max_hit_node;

    void print(ostream &out) const {
        out << "min_hops: " << min_hops << endl;
        out << "max_hops: " << max_hops << endl;
        out << "mean_hops: " << mean_hops << endl;
        out << "q1_hops: " << q1_hops << endl;
        out << "q2_hops: " << q2_hops << endl;
        out << "q3_hops: " << q3_hops << endl;
        out << "max_hit_prob: " << max_hit_prob << endl;
        out << "max_hit_node: " << max_hit_node << endl;
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

int main(int argc, char **argv) {
    Options opts = parse_args(argc, argv);
    Graph graph = opts.edges_csv.empty() ? Graph(cin) : Graph(opts.edges_csv);
    const auto &adj = graph.adj_list();

    int src_idx = graph.node_index(opts.src_node);
    int tgt_idx = graph.node_index(opts.tgt_node);

    const int node_count = static_cast<int>(adj.size());
    vector<int> hop_counts(opts.no_of_runs, 0);
    vector<int> hit_count(node_count, 0);

    auto make_token = [&](int seed) -> unique_ptr<RwToken> {
        if (opts.rw_variant == "R") return make_unique<RToken>(src_idx, tgt_idx, seed);
        if (opts.rw_variant == "NB") return make_unique<NbToken>(src_idx, tgt_idx, seed);
        if (opts.rw_variant == "LRV") return make_unique<LrvToken>(src_idx, tgt_idx, seed);
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
            while (position != tgt_idx) {
                position = token->choose_next_and_update(adj[position]);
                seen_nodes.insert(position);
                hops++;
            }
            hop_counts[i] = hops;
            for (int node : seen_nodes) {
                local_hits[node]++;
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
    stats.print(cout);
    return 0;
}

void print_usage(const char *prog_name) {
    cerr << "Usage: " << prog_name
         << " --src-node <node> --tgt-node <node> "
            "[--no-of-runs <int>] [--rw-variant <name>] [--edges-csv <path>]" << endl;
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

        if(flag == "--no-of-runs"){
            opts.no_of_runs = stoi(require_value(i, flag, has_inline, inline_value));
        }
        else if(flag == "--src-node"){
            opts.src_node = require_value(i, flag, has_inline, inline_value);
        }
        else if(flag == "--tgt-node"){
            opts.tgt_node = require_value(i, flag, has_inline, inline_value);
        }
        else if(flag == "--rw-variant"){
            opts.rw_variant = require_value(i, flag, has_inline, inline_value);
        }
        else if(flag == "--edges-csv"){
            opts.edges_csv = require_value(i, flag, has_inline, inline_value);
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