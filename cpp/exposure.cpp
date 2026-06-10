#include <algorithm>
#include <cctype>
#include <functional>
#include <iomanip>
#include <iostream>
#include <memory>
#include <numeric>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <unordered_map>
#include <vector>

#include "cli.hpp"
#include "graph.hpp"
#include "lerw.hpp"
#include "walk.hpp"

using namespace std;

struct Options {
    WalkCliOpts walk;
    int cartel_size = 1;
    bool dump_hits = false;
    string context;
};

struct HitCounts {
    // Marginals over loop-erased s->t walks (one run = one sample):
    // single[u]     = #runs visiting u
    // pair[u,v]     = #runs visiting both u and v  (u < v)
    // triple[u,v,w] = #runs visiting u, v, and w   (u < v < w)
    vector<int> single;
    vector<vector<int>> pair;
    unordered_map<uint64_t, int> triple;
};

static uint64_t triple_key(int u, int v, int w, int n) {
    return (
        (static_cast<uint64_t>(u) * n + static_cast<uint64_t>(v)) * n +
        static_cast<uint64_t>(w)
    );
}

static void record_path_hits(const vector<int> &path, HitCounts &hits, int n) {
    // Accumulate single/pair/triple co-occurrence counts for one LERW path.
    // Loop-erased paths visit each node at most once; skip sort/dedup.
    const size_t len = path.size();
    for (int u : path) {
        hits.single[u]++;
    }
    for (size_t i = 0; i < len; i++) {
        const int u = path[i];
        for (size_t j = i + 1; j < len; j++) {
            const int v = path[j];
            const int a = min(u, v);
            const int b = max(u, v);
            hits.pair[a][b]++;
            for (size_t k = j + 1; k < len; k++) {
                int nodes[3] = {u, path[j], path[k]};
                sort(nodes, nodes + 3);
                hits.triple[triple_key(nodes[0], nodes[1], nodes[2], n)]++;
            }
        }
    }
}

// #runs where at least one cartel node lies on the loop-erased walk.
//
// Exposure is P(at least one cartel node on path). We never store per-run bitsets;
// instead inclusion-exclusion on the marginals in HitCounts:
//   |A ∪ B|     = |A| + |B| - |A ∩ B|
//   |A ∪ B ∪ C| = |A| + |B| + |C| - pairwise intersections + |A ∩ B ∩ C|
// Cartel size is limited to 3 because we only aggregate up to triple hits.
static int cartel_union_hit_count(const vector<int> &cartel, const HitCounts &hits) {
    const int n = static_cast<int>(hits.single.size());
    if (cartel.size() == 1) {
        return hits.single[cartel[0]];
    }
    int u = cartel[0];
    int v = cartel[1];
    if (u > v) swap(u, v);
    int union_hits = hits.single[cartel[0]] + hits.single[cartel[1]] - hits.pair[u][v];
    if (cartel.size() == 3) {
        int a = cartel[0];
        int b = cartel[1];
        int c = cartel[2];
        vector<int> sorted = {a, b, c};
        sort(sorted.begin(), sorted.end());
        auto it = hits.triple.find(triple_key(sorted[0], sorted[1], sorted[2], n));
        int tri = it == hits.triple.end() ? 0 : it->second;
        union_hits += hits.single[c] -
            hits.pair[min(a, c)][max(a, c)] -
            hits.pair[min(b, c)][max(b, c)] +
            tri;
    }
    return union_hits;
}

static double cartel_exposure(
    const vector<int> &cartel,
    int runs,
    const HitCounts &hits
) {
    return static_cast<double>(cartel_union_hit_count(cartel, hits)) / runs;
}

static uint64_t cartel_key(const vector<int> &cartel, int n) {
    uint64_t key = 0;
    for (int u : cartel) {
        key = key * static_cast<uint64_t>(n) + static_cast<uint64_t>(u);
    }
    return key;
}

// Eligible cartel: neither endpoint is in C, and s remains connected to t in G \\ C.
static bool cartel_is_eligible(
    const vector<int> &cartel,
    int src,
    int tgt,
    const vector<vector<int>> &adj,
    vector<char> &blocked,
    vector<char> &seen,
    queue<int> &q
) {
    fill(blocked.begin(), blocked.end(), 0);
    fill(seen.begin(), seen.end(), 0);
    for (int u : cartel) {
        if (u == src || u == tgt) return false;
        blocked[u] = 1;
    }
    seen[src] = 1;
    q.push(src);
    while (!q.empty()) {
        const int u = q.front();
        q.pop();
        if (u == tgt) return true;
        for (int v : adj[u]) {
            if (!blocked[v] && !seen[v]) {
                seen[v] = 1;
                q.push(v);
            }
        }
    }
    return false;
}

static void dump_hit_counts(
    ostream &out,
    const Graph &graph,
    int runs,
    const HitCounts &hits
) {
    const int n = graph.node_count();
    out << "runs: " << runs << '\n';
    out << "n: " << n << '\n';
    out << "nodes:";
    for (int u = 0; u < n; u++) {
        out << ' ' << graph.node_name(u);
    }
    out << '\n';
    out << "single:";
    for (int u = 0; u < n; u++) {
        out << ' ' << hits.single[u];
    }
    out << '\n';
    out << "pair:";
    for (int u = 0; u < n; u++) {
        for (int v = u + 1; v < n; v++) {
            out << ' ' << hits.pair[u][v];
        }
    }
    out << '\n';
    out << "triple_count: " << hits.triple.size() << '\n';
    for (const auto &[key, count] : hits.triple) {
        const int w = static_cast<int>(key % n);
        const int rem = static_cast<int>(key / n);
        const int v = rem % n;
        const int u = rem / n;
        out << "triple: " << u << ' ' << v << ' ' << w << ' ' << count << '\n';
    }
}

static void merge_hits(HitCounts &dst, const HitCounts &src, int n) {
    for (int u = 0; u < n; u++) {
        dst.single[u] += src.single[u];
        for (int v = u + 1; v < n; v++) {
            dst.pair[u][v] += src.pair[u][v];
        }
    }
    for (const auto &[key, count] : src.triple) {
        dst.triple[key] += count;
    }
}

static string format_cartel_nodes(const Graph &graph, const vector<int> &cartel) {
    ostringstream out;
    for (size_t i = 0; i < cartel.size(); i++) {
        if (i > 0) out << ' ';
        out << graph.node_name(cartel[i]);
    }
    return out.str();
}

static Options parse_args(int argc, char **argv) {
    Options opts;
    CliParser cli(argc, argv);
    WalkFlagOpts walk_flags;
    walk_flags.endpoints_optional = true;
    cli.reg_walk_flags(opts.walk, walk_flags);
    cli.reg_bool("--dump-hits", {}, opts.dump_hits);
    cli.reg_int("--cartel-size", "-m", opts.cartel_size, !opts.dump_hits);
    cli.parse();
    resolve_walk_graph(opts.walk);
    validate_walk_endpoints_pair(cli, opts.walk);
    if (opts.walk.src_node.empty()) {
        cli.fail("Source and target nodes are required for exposure simulation");
    }
    if (!opts.dump_hits && (opts.cartel_size < 1 || opts.cartel_size > 3)) {
        cli.fail("Cartel size must be 1, 2, or 3 (inclusion-exclusion limit)");
    }
    validate_positive_runs(cli, opts.walk.no_of_runs);
    opts.context = cli.format_context();
    return opts;
}

int main(int argc, char **argv) {
    Options opts = parse_args(argc, argv);
    Graph graph(opts.walk.edges_csv);
    const vector<vector<int>> &adj = graph.adj_list();
    const int n = graph.node_count();
    const int src = graph.node_index(opts.walk.src_node);
    const int tgt = graph.node_index(opts.walk.tgt_node);

    const RwVariant variant = parse_rw_variant(opts.walk.rw_variant);
    if (variant == RwVariant::Unknown) {
        cerr << "Unknown random walk variant: " << opts.walk.rw_variant << endl;
        return 1;
    }

    const unsigned int hw_threads = thread::hardware_concurrency();
    int thread_count = static_cast<int>(hw_threads == 0 ? 1 : hw_threads);
    thread_count = min(thread_count, opts.walk.no_of_runs);

    vector<HitCounts> local_hits(thread_count);
    for (HitCounts &lh : local_hits) {
        lh.single.assign(n, 0);
        lh.pair.assign(n, vector<int>(n, 0));
    }

    // Phase 1: Monte Carlo — sample LERW paths and aggregate hit marginals.
    auto run_chunk = [&](int tid, int start_run, int end_run) {
        HitCounts &hits = local_hits[tid];
        WalkSampleScratch scratch;
        scratch.prepare_buffers(n);
        vector<int> lerw;
        for (int run = start_run; run < end_run; run++) {
            sample_loop_erased_path(scratch, lerw, adj, variant, src, tgt, run, n);
            record_path_hits(lerw, hits, n);
        }
    };

    vector<thread> workers;
    workers.reserve(thread_count);
    int base_runs = opts.walk.no_of_runs / thread_count;
    int extra_runs = opts.walk.no_of_runs % thread_count;
    int next_start = 0;
    for (int tid = 0; tid < thread_count; tid++) {
        const int chunk = base_runs + (tid < extra_runs ? 1 : 0);
        const int start_run = next_start;
        const int end_run = start_run + chunk;
        workers.emplace_back(run_chunk, tid, start_run, end_run);
        next_start = end_run;
    }
    try {
        for (thread &worker : workers) {
            worker.join();
        }
    } catch (const exception &ex) {
        cerr << ex.what() << endl;
        return 1;
    }

    HitCounts hits;
    hits.single.assign(n, 0);
    hits.pair.assign(n, vector<int>(n, 0));
    for (const HitCounts &lh : local_hits) {
        merge_hits(hits, lh, n);
    }

    if (opts.dump_hits) {
        cout << opts.context;
        dump_hit_counts(cout, graph, opts.walk.no_of_runs, hits);
        return 0;
    }

    vector<int> cartel(opts.cartel_size);
    double sum_all = 0.0;
    double sum_eligible = 0.0;
    long long count_all = 0;
    long long count_eligible = 0;
    double max_exposure_eligible = -1.0;
    vector<int> max_exposure_eligible_cartel;
    vector<char> blocked(n, 0);
    vector<char> seen(n, 0);
    queue<int> bfs_q;
    unordered_map<uint64_t, bool> eligible_cache;

    // Phase 2: enumerate all cartels of size m; exposure via inclusion-exclusion.
    function<void(int, int)> walk_combinations = [&](int start, int depth) {
        if (depth == opts.cartel_size) {
            const double exposure = cartel_exposure(cartel, opts.walk.no_of_runs, hits);
            sum_all += exposure;
            count_all++;
            const uint64_t key = cartel_key(cartel, n);
            auto it = eligible_cache.find(key);
            bool eligible;
            if (it == eligible_cache.end()) {
                eligible = cartel_is_eligible(cartel, src, tgt, adj, blocked, seen, bfs_q);
                eligible_cache[key] = eligible;
            } else {
                eligible = it->second;
            }
            if (eligible) {
                sum_eligible += exposure;
                count_eligible++;
                if (exposure > max_exposure_eligible) {
                    max_exposure_eligible = exposure;
                    max_exposure_eligible_cartel = cartel;
                }
            }
            return;
        }
        for (int i = start; i <= n - (opts.cartel_size - depth); i++) {
            cartel[depth] = i;
            walk_combinations(i + 1, depth + 1);
        }
    };
    walk_combinations(0, 0);

    cout << fixed << setprecision(6);
    cout << opts.context;
    cout << "mean_exposure_all: "
         << (count_all ? sum_all / count_all : 0.0) << endl;
    cout << "mean_exposure_eligible: "
         << (count_eligible ? sum_eligible / count_eligible : 0.0) << endl;
    if (count_eligible > 0) {
        cout << "max_exposure_eligible: " << max_exposure_eligible << endl;
        cout << "max_exposure_eligible_cartel: "
             << format_cartel_nodes(graph, max_exposure_eligible_cartel) << endl;
    } else {
        cout << "max_exposure_eligible: n/a" << endl;
        cout << "max_exposure_eligible_cartel: n/a" << endl;
    }
    cout << "total_cartels: " << count_all << endl;
    cout << "eligible_cartels: " << count_eligible << endl;
    return 0;
}
