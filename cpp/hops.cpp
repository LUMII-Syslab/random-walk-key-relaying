#include <algorithm>
#include <cmath>
#include <cctype>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <sstream>
#include <string>
#include <string_view>
#include <thread>
#include <vector>

#include "cli.hpp"
#include "graph.hpp"
#include "lerw.hpp"
#include "walk.hpp"

using namespace std;

struct Options {
    WalkCliOpts walk;
    bool record_paths = false;
    bool erase_loops = false;
};

struct HopSummary {
    int min_hops = 0;
    int p25 = 0;
    int p50 = 0;
    int p75 = 0;
    int p90 = 0;
    int p95 = 0;
    int p99 = 0;
    int max_hops = 0;
    double mean = 0.0;
    double sd = 0.0;
    double ci_low = 0.0;
    double ci_high = 0.0;
};

static int percentile(const vector<int> &sorted, double p) {
    if (sorted.empty()) return 0;
    const int idx = static_cast<int>((sorted.size() - 1) * p);
    return sorted[idx];
}

static HopSummary summarize_hops(const vector<int> &hop_counts) {
    vector<int> sorted = hop_counts;
    sort(sorted.begin(), sorted.end());

    const int n = static_cast<int>(hop_counts.size());
    const double sum = accumulate(hop_counts.begin(), hop_counts.end(), 0.0);
    const double mean = n ? sum / n : 0.0;

    double var = 0.0;
    for (int hops : hop_counts) {
        const double d = hops - mean;
        var += d * d;
    }
    const double sd = n > 1 ? sqrt(var / (n - 1)) : 0.0;
    const double margin = n ? 1.96 * sd / sqrt(static_cast<double>(n)) : 0.0;

    HopSummary s;
    s.min_hops = sorted.front();
    s.p25 = percentile(sorted, 0.25);
    s.p50 = percentile(sorted, 0.50);
    s.p75 = percentile(sorted, 0.75);
    s.p90 = percentile(sorted, 0.90);
    s.p95 = percentile(sorted, 0.95);
    s.p99 = percentile(sorted, 0.99);
    s.max_hops = sorted.back();
    s.mean = mean;
    s.sd = sd;
    s.ci_low = mean - margin;
    s.ci_high = mean + margin;
    return s;
}

static void print_summary(ostream &out, const Options &opts, const HopSummary &s) {
    out << "context: " << opts.walk.src_node << " -> " << opts.walk.tgt_node
        << " (" << opts.walk.rw_variant << ", " << opts.walk.no_of_runs << " runs";
    if (opts.erase_loops) out << ", loop-erased";
    out << ")" << endl;
    out << "min: " << s.min_hops << endl;
    out << "p25: " << s.p25 << endl;
    out << "median / p50: " << s.p50 << endl;
    out << "p75: " << s.p75 << endl;
    out << "p90: " << s.p90 << endl;
    out << "p95: " << s.p95 << endl;
    out << "p99: " << s.p99 << endl;
    out << "max: " << s.max_hops << endl;
    out << fixed << setprecision(1);
    out << "mean: " << s.mean << endl;
    out << "sd: " << s.sd << endl;
    out << "95% CI for mean: [" << s.ci_low << ", " << s.ci_high << "]" << endl;
}

static Options parse_args(int argc, char **argv) {
    Options opts;
    opts.walk.no_of_runs = 1000;
    CliParser cli(argc, argv);
    cli.reg_walk_flags(opts.walk);
    cli.reg_bool("--record-paths", {}, opts.record_paths);
    cli.reg_bool("--erase-loops", {}, opts.erase_loops);
    cli.parse();
    resolve_walk_graph(opts.walk);
    validate_walk_endpoints(cli, opts.walk);
    validate_positive_runs(cli, opts.walk.no_of_runs);
    return opts;
}

int main(int argc, char **argv) {
    Options opts = parse_args(argc, argv);
    Graph graph(opts.walk.edges_csv);
    const auto &adj = graph.adj_list();
    const int src = graph.node_index(opts.walk.src_node);
    const int tgt = graph.node_index(opts.walk.tgt_node);
    const int n = graph.node_count();

    const RwVariant variant = parse_rw_variant(opts.walk.rw_variant);
    if (variant == RwVariant::Unknown) {
        cerr << "Unknown random walk variant: " << opts.walk.rw_variant << endl;
        return 1;
    }

    vector<int> hop_counts(opts.walk.no_of_runs);
    vector<vector<string>> paths;
    if (opts.record_paths) {
        paths.resize(opts.walk.no_of_runs);
    }

    const unsigned int hw = thread::hardware_concurrency();
    int thread_count = static_cast<int>(hw == 0 ? 1 : hw);
    thread_count = min(thread_count, opts.walk.no_of_runs);

    auto run_chunk = [&](int start_run, int end_run) {
        WalkSampleScratch scratch;
        scratch.prepare_buffers(n);
        vector<int> lerw;
        for (int run = start_run; run < end_run; run++) {
            sample_random_walk_history(scratch, adj, variant, src, tgt, run, n);
            if (opts.erase_loops) {
                lerw = erase_loops_from_history(scratch.history);
            }
            const vector<int> &effective = opts.erase_loops ? lerw : scratch.history;
            hop_counts[run] = static_cast<int>(effective.size()) - 1;

            if (opts.record_paths) {
                vector<string> names;
                names.reserve(effective.size());
                for (int node : effective) {
                    names.push_back(graph.node_name(node));
                }
                paths[run] = std::move(names);
            }
        }
    };

    vector<thread> workers;
    workers.reserve(thread_count);
    int base = opts.walk.no_of_runs / thread_count;
    int extra = opts.walk.no_of_runs % thread_count;
    int next = 0;
    for (int tid = 0; tid < thread_count; tid++) {
        const int chunk = base + (tid < extra ? 1 : 0);
        const int start = next;
        next += chunk;
        workers.emplace_back(run_chunk, start, next);
    }
    try {
        for (thread &w : workers) w.join();
    } catch (const exception &ex) {
        cerr << ex.what() << endl;
        return 1;
    }

    print_summary(cout, opts, summarize_hops(hop_counts));

    if (opts.record_paths) {
        cout << "path_count: " << paths.size() << endl;
        const int width = static_cast<int>(to_string(paths.size() - 1).size());
        for (size_t i = 0; i < paths.size(); i++) {
            string label = to_string(i);
            while (static_cast<int>(label.size()) < width) label = "0" + label;
            cout << "path " << label << ":";
            for (const string &node : paths[i]) cout << " " << node;
            cout << endl;
        }
    }
    return 0;
}
