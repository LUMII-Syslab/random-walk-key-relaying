#include <algorithm>
#include <cctype>
#include <iostream>
#include <memory>
#include <queue>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <chrono>
#include <array>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <variant>
#include <vector>

#include "graph.hpp"
#include "walk.hpp"

using namespace std;

static constexpr double kClassicLatencyS = 0.005; // 5 ms
static constexpr int kChunkBits = 256;
static constexpr double kQkdSkrBitsPerS = 1000.0; // 1 kbit/s
static constexpr int kMinTtl = 1;
static constexpr int kMaxTtl = 100;
static constexpr double kDropIfAnyLinkWaitGtS = 10.0;

struct ReportedRecvChunkEvent {
    double time = 0.0;
    string src;
    string tgt;
    vector<string> path; // s..t inclusive
};

struct ReportedKeyEstablEvent {
    double time = 0.0;
    string src;
    string tgt;
    int key_count = 0;
};

using ReportedEvent = variant<ReportedRecvChunkEvent, ReportedKeyEstablEvent>;

static string trim_copy(string s) {
    while (!s.empty() && isspace(static_cast<unsigned char>(s.back()))) s.pop_back();
    size_t i = 0;
    while (i < s.size() && isspace(static_cast<unsigned char>(s[i]))) i++;
    return s.substr(i);
}

static vector<string> parse_src_nodes_csv(const string &s) {
    vector<string> out;
    stringstream ss(s);
    string part;
    while (getline(ss, part, ',')) {
        part = trim_copy(part);
        if (!part.empty()) out.push_back(part);
    }
    return out;
}

struct Options {
    vector<string> src_nodes;
    string rw_variant;
    double duration_s = 0.0;
    string edges_csv = "";
    vector<string> delete_nodes; // node names to delete from graph

    // Phase 1: scout emission rate (per source)
    double scout_rate_per_s = 1.0;

    // Phase 4: block formation
    int block_chunks = 32;
    // Upper bound for extracted keys per completed block.
    // Defaults to block_chunks (set after parsing).
    int max_block_keys = -1;
    int cartel_size = 1; // adversary nodes per (src,tgt), currently supports 0, 1 or 2

    // Congestion / willingness to accept
    int watermark_sz = 16;

    // Optional early-stop condition:
    // stop once for every node v and every source s != v, established_keys(s->v) >= min_keys_per_pair.
    int min_keys_per_pair = 0; // 0 disables

    // Periodic wall-clock progress logging.
    bool verbose = false;

    // RNG seed (controls accept decisions and per-scout RW seeds).
    uint64_t seed = 1234567;
};

static void print_usage(const char *prog_name) {
    cerr << "Usage: " << prog_name
         << " (--src-nodes|-S) <n1,n2,...> (--rw-variant|-w) <name> "
            "(--duration-s|-d) <seconds> "
            "[(--edges-csv|-e) <path>] "
            "[--delete-nodes <n1,n2,...>] "
            "[--scout-rate <float>] [--block-chunks <int>] [--max-block-keys <int>] [--watermark-sz <int>]"
            " [--cartel-size <int>]"
            " [--min-keys-per-pair <int>]"
            " [--seed <uint64>]"
            " [--verbose]"
         << endl;
}

static bool valid_rw_variant(const string &w) {
    return w == "R" || w == "NB" || w == "LRV" || w == "NC" || w == "HS";
}

static Options parse_args(int argc, char **argv) {
    Options opts;
    auto fail = [&](const string &msg) -> void {
        cerr << msg << endl;
        print_usage(argv[0]);
        exit(1);
    };

    auto require_value = [&](int &i, string_view flag, bool has_inline, string_view inline_value) -> string {
        if (has_inline) {
            if (inline_value.empty()) fail("Missing value for " + string(flag));
            return string(inline_value);
        }
        if (i + 1 >= argc) fail("Missing value for " + string(flag));
        return argv[++i];
    };

    bool have_src_nodes = false;
    bool have_rw = false;
    bool have_duration = false;

    for (int i = 1; i < argc; i++) {
        string_view arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            print_usage(argv[0]);
            exit(0);
        }

        size_t eq_pos = arg.find('=');
        bool has_inline = eq_pos != string_view::npos;
        string_view flag = has_inline ? arg.substr(0, eq_pos) : arg;
        string_view inline_value = has_inline ? arg.substr(eq_pos + 1) : string_view{};

        if (flag == "--src-nodes" || flag == "-S") {
            opts.src_nodes = parse_src_nodes_csv(require_value(i, flag, has_inline, inline_value));
            have_src_nodes = true;
        } else if (flag == "--rw-variant" || flag == "-w") {
            opts.rw_variant = require_value(i, flag, has_inline, inline_value);
            have_rw = true;
        } else if (flag == "--duration-s" || flag == "-d") {
            opts.duration_s = stod(require_value(i, flag, has_inline, inline_value));
            have_duration = true;
        } else if (flag == "--edges-csv" || flag == "-e") {
            opts.edges_csv = require_value(i, flag, has_inline, inline_value);
        } else if (flag == "--delete-nodes") {
            opts.delete_nodes = parse_src_nodes_csv(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--scout-rate") {
            opts.scout_rate_per_s = stod(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--block-chunks") {
            opts.block_chunks = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--max-block-keys") {
            opts.max_block_keys = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--block-keys") {
            // Back-compat alias (deprecated): --block-keys -> --max-block-keys
            opts.max_block_keys = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--watermark-sz") {
            opts.watermark_sz = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--cartel-size") {
            opts.cartel_size = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--min-keys-per-pair") {
            opts.min_keys_per_pair = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--seed") {
            opts.seed = stoull(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--verbose") {
            opts.verbose = true;
        } else {
            fail("Unknown argument: " + string(arg));
        }
    }

    if (!have_src_nodes || opts.src_nodes.empty()) fail("Non-empty --src-nodes is required");
    if (!have_rw || opts.rw_variant.empty()) fail("--rw-variant is required");
    if (!valid_rw_variant(opts.rw_variant)) fail("Unknown random walk variant: " + opts.rw_variant);
    if (!have_duration) fail("--duration-s is required");
    if (opts.duration_s <= 0.0) fail("--duration-s must be > 0");
    if (opts.scout_rate_per_s <= 0.0) fail("--scout-rate must be > 0");
    if (opts.block_chunks <= 0) fail("--block-chunks must be > 0");
    if (opts.max_block_keys == -1) opts.max_block_keys = opts.block_chunks;
    if (opts.max_block_keys <= 0) fail("--max-block-keys must be > 0");
    if (opts.watermark_sz <= 0) fail("--watermark-sz must be > 0");
    if (opts.cartel_size != 0 && opts.cartel_size != 1 && opts.cartel_size != 2) fail("--cartel-size must be 0, 1 or 2");
    if (opts.min_keys_per_pair < 0) fail("--min-keys-per-pair must be >= 0");

    return opts;
}

static unique_ptr<RwToken> make_base_token(const string &rw_variant, int src_idx, int tgt_idx, int seed, int node_count) {
    if (rw_variant == "R") return make_unique<RToken>(src_idx, tgt_idx, seed);
    if (rw_variant == "NB") return make_unique<NbToken>(src_idx, tgt_idx, seed);
    if (rw_variant == "LRV") return make_unique<LrvToken>(src_idx, tgt_idx, seed);
    if (rw_variant == "NC") return make_unique<NcToken>(src_idx, tgt_idx, seed, node_count);
    if (rw_variant == "HS") return make_unique<HsToken>(src_idx, tgt_idx, seed);
    return nullptr;
}

static int derive_scout_seed(uint64_t base_seed, uint64_t scout_idx) {
    // Use splitmix64-style mixing to avoid correlations between successive seeds
    // (important when downstream uses rng()%deg for small degrees).
    auto mix64 = [](uint64_t x) -> uint64_t {
        x += 0x9e3779b97f4a7c15ull;
        x = (x ^ (x >> 30)) * 0xbf58476d1ce4e5b9ull;
        x = (x ^ (x >> 27)) * 0x94d049bb133111ebull;
        x = x ^ (x >> 31);
        return x;
    };
    uint64_t x = base_seed ^ mix64(scout_idx);
    uint64_t y = mix64(x);
    return static_cast<int>(static_cast<uint32_t>(y ^ (y >> 32)));
}

static double consume_probability(int hops, int max_ttl, int buffered_keys_for_src, int watermark_sz) {
    if (watermark_sz <= 0) return 1.0;
    // Hard congestion cut-off: if already at/above watermark, do not accept new scouts.
    // This prevents repeatedly feeding already-satisfied nodes when watermark is small (e.g. 1).
    if (buffered_keys_for_src >= watermark_sz) return 0.0;
    const double b = min(1.0, static_cast<double>(buffered_keys_for_src) / static_cast<double>(watermark_sz));
    const double t_remaining = static_cast<double>(max_ttl - hops) / static_cast<double>(max_ttl);
    const double p = 1.0 - b * t_remaining;
    if (p < 0.0) return 0.0;
    if (p > 1.0) return 1.0;
    return p;
}

static vector<int> loop_erase_path(const vector<int> &walk) {
    vector<int> out;
    out.reserve(walk.size());
    unordered_map<int, size_t> pos;
    pos.reserve(walk.size());

    for (int node : walk) {
        auto it = pos.find(node);
        if (it == pos.end()) {
            pos[node] = out.size();
            out.push_back(node);
            continue;
        }
        const size_t keep = it->second;
        for (size_t j = keep + 1; j < out.size(); j++) {
            pos.erase(out[j]);
        }
        out.resize(keep + 1);
    }
    return out;
}

// Queue-based link: backlog is measured in "chunk-sized reservations".
struct LinkQueueState {
    double backlog_units = 0.0; // can be fractional after updates
    double last_update = 0.0;

    static constexpr double service_time_s() {
        return static_cast<double>(kChunkBits) / kQkdSkrBitsPerS;
    }

    void update(double now) {
        if (now < last_update) throw runtime_error("link queue time went backwards");
        const double dt = now - last_update;
        const double served_units = dt / service_time_s();
        backlog_units = max(0.0, backlog_units - served_units);
        last_update = now;
    }

    // Observed waiting time for a hypothetical new scout at time `now` (does not enqueue).
    double observe_wait_s(double now) {
        update(now);
        return backlog_units * service_time_s();
    }

    // Enqueue one scout/chunk-reservation at time `now`. Returns wait until its service completes.
    double enqueue_and_get_ready_time(double now) {
        update(now);
        const double wait_before_service = backlog_units * service_time_s();
        backlog_units += 1.0;
        // When will this reservation be fully established?
        return now + wait_before_service + service_time_s();
    }
};

struct QueueQkdNetwork {
    Graph graph;
    // undirected edge queue (shared both directions)
    map<EdgeKey, LinkQueueState> link_q;

    explicit QueueQkdNetwork(Graph g) : graph(std::move(g)) {
        for (const EdgeKey &e : graph.edges()) link_q.emplace(e, LinkQueueState{});
    }

    LinkQueueState &link_state(int a, int b) {
        auto it = link_q.find(EdgeKey(a, b));
        if (it == link_q.end()) throw runtime_error("not an edge");
        return it->second;
    }
};

struct Scout {
    int src = -1;
    int hops = 0;
    vector<int> walk_nodes; // s..current inclusive
    unique_ptr<RwToken> token;

    int tgt = -1;
    vector<int> path; // loop-erased s..t inclusive

    // Filled when a node accepts the scout (before return walk).
    int raw_walk_vertices_at_accept = 0;
    int hops_at_accept = 0;

    // per-hop OTP ready times computed on return; indexed by hop i (edge path[i]->path[i+1])
    vector<double> hop_ready_time;
};

struct Chunk {
    int src = -1;
    int tgt = -1;
    vector<int> path; // s..t inclusive
    int pos = 0;
    // Snapshot from scouting (accept defines tgt; hops = graph hops from src to acceptor).
    int raw_walk_vertices_at_accept = 0;
    int hops_at_accept = 0;
};

struct BlockPathEntry {
    vector<int> path;
    int scout_raw_walk_vertices = 0;
    int scout_hops_at_accept = 0;
};

enum class EventType {
    EmitScout,
    ScoutArrive,
    ScoutReturnStep,
    StartChunk,
    ChunkArriveHop,
};

struct Event {
    double time = 0.0;
    EventType type = EventType::EmitScout;
    int src_for_emit = -1;
    shared_ptr<Scout> scout;
    shared_ptr<Chunk> chunk;
    int from = -1;
    int to = -1;
    int return_pos = -1; // for ScoutReturnStep: current index in path (starting at tgt)
};

struct EventGreater {
    bool operator()(const Event &a, const Event &b) const { return a.time > b.time; }
};

static void print_event_line(const ReportedEvent &ev, ostream &out) {
    visit([&](auto &&e) {
        using T = decay_t<decltype(e)>;
        if constexpr (is_same_v<T, ReportedKeyEstablEvent>) {
            out << "key_establ " << e.time << " " << e.src << " " << e.tgt << " " << e.key_count << "\n";
        } else {
            out << "recv_chunk " << e.time << " " << e.src << " " << e.tgt;
            for (const string &hop : e.path) out << " " << hop;
            out << "\n";
        }
    }, ev);
}

struct SimulationOutput {
    vector<ReportedEvent> reported;
};

static Graph build_filtered_graph(const Graph &g, const vector<string> &delete_nodes) {
    if (delete_nodes.empty()) return g;
    unordered_set<string> del;
    del.reserve(delete_nodes.size() * 2 + 1);
    for (const string &nm : delete_nodes) {
        string t = trim_copy(nm);
        if (!t.empty()) del.insert(t);
    }
    if (del.empty()) return g;

    // Keep edges whose endpoints are not deleted; rebuild a Graph via stdin format.
    vector<pair<string, string>> kept_edges;
    kept_edges.reserve(g.edges().size());
    unordered_set<string> kept_nodes;
    kept_nodes.reserve(g.node_count() * 2 + 1);
    for (const EdgeKey &ek : g.edges()) {
        const string &u = g.node_name(ek.u);
        const string &v = g.node_name(ek.v);
        if (del.count(u) || del.count(v)) continue;
        kept_edges.emplace_back(u, v);
        kept_nodes.insert(u);
        kept_nodes.insert(v);
    }

    stringstream ss;
    ss << kept_nodes.size() << " " << kept_edges.size() << "\n";
    for (const auto &e : kept_edges) {
        ss << e.first << " " << e.second << "\n";
    }
    return Graph(ss);
}

static bool exists_path_avoiding_nodes(const Graph &graph, int src, int tgt, const vector<int> &forbidden) {
    if (src == tgt) return true;
    vector<char> blocked(graph.node_count(), 0);
    for (int v : forbidden) {
        if (v < 0 || v >= graph.node_count()) continue;
        blocked[v] = 1;
    }
    blocked[src] = 0;
    blocked[tgt] = 0;

    deque<int> q;
    vector<char> seen(graph.node_count(), 0);
    q.push_back(src);
    seen[src] = 1;
    while (!q.empty()) {
        int u = q.front();
        q.pop_front();
        if (u == tgt) return true;
        for (int v : graph.neighbors(u)) {
            if (blocked[v] || seen[v]) continue;
            seen[v] = 1;
            q.push_back(v);
        }
    }
    return false;
}

static SimulationOutput run_simulation(const Options &opts, const Graph &graph) {
    QueueQkdNetwork qkd{Graph(graph)}; // own link queues
    const int n = graph.node_count();
    const auto &adj = graph.adj_list();

    vector<char> is_src(n, 0);
    vector<int> src_indices;
    for (const string &name : opts.src_nodes) {
        int idx = graph.node_index(name);
        if (!is_src[idx]) src_indices.push_back(idx);
        is_src[idx] = 1;
    }

    mt19937 rng(static_cast<uint32_t>(opts.seed));
    uniform_real_distribution<double> u01(0.0, 1.0);
    priority_queue<Event, vector<Event>, EventGreater> pq;

    // Congestion term: per-target, per-source buffered KEYS (used only for accept prob).
    // This is a simulation proxy for "how many established keys does tgt currently hold for src".
    vector<unordered_map<int, int>> buffered_keys(n);

    // Block formation count.
    vector<unordered_map<int, int>> block_recv_count(n);

    // Established keys count (tgt -> (src -> count)).
    vector<unordered_map<int, int>> established_keys(n);

    // Per (tgt, src): store loop-erased paths (+ scout walk stats) for the current block window.
    vector<unordered_map<int, vector<BlockPathEntry>>> block_paths(n);

    auto early_stop_satisfied = [&]() -> bool {
        if (opts.min_keys_per_pair <= 0) return false;
        for (int v = 0; v < n; v++) {
            for (int s : src_indices) {
                if (s == v) continue;
                auto it = established_keys[v].find(s);
                const int have = (it == established_keys[v].end()) ? 0 : it->second;
                if (have < opts.min_keys_per_pair) return false;
            }
        }
        return true;
    };

    auto schedule_emit_scout = [&](double now, int src_idx) {
        pq.push(Event{now, EventType::EmitScout, src_idx, nullptr, nullptr, -1, -1, -1});
    };

    for (int s : src_indices) schedule_emit_scout(0.0, s);

    vector<ReportedEvent> reported;

    // Verbose wall-clock logging (every ~5 seconds).
    uint64_t processed_events = 0;
    uint64_t scouts_emitted = 0;
    uint64_t scouts_accepted = 0;
    uint64_t scouts_dropped_wait = 0;
    uint64_t scouts_dropped_ttl_gt_1000 = 0;
    uint64_t scouts_dropped_return_src = 0;
    uint64_t scouts_dropped_max_ttl = 0;
    array<uint64_t, 6> scout_accept_hop_hist{}; // bins: hops 1,2,3,4,5,6+
    uint64_t chunks_started = 0;
    uint64_t chunks_received = 0;
    uint64_t keys_established_events = 0;

    using Clock = chrono::steady_clock;
    const auto wall_start = Clock::now();
    auto wall_last_log = wall_start;
    uint64_t processed_at_last_log = 0;
    uint64_t scout_counter = 0;

    while (!pq.empty()) {
        Event ev = pq.top();
        pq.pop();
        processed_events++;
        if (ev.time > opts.duration_s) break;

        if (opts.verbose) {
            const auto wall_now = Clock::now();
            const auto dt = wall_now - wall_last_log;
            if (dt >= chrono::seconds(5)) {
                const double wall_s = chrono::duration<double>(wall_now - wall_start).count();
                const double dt_s = chrono::duration<double>(dt).count();
                const double evps = dt_s > 0 ? (static_cast<double>(processed_events - processed_at_last_log) / dt_s) : 0.0;

                cerr.setf(ios::fixed);
                cerr.precision(2);
                cerr << "[scouted] wall=" << wall_s << "s"
                     << " sim=" << ev.time << "s"
                     << " pq=" << pq.size()
                     << " ev=" << processed_events
                     << " ev/s=" << evps
                     << " scouts(em/acc)=" << scouts_emitted << "/" << scouts_accepted
                     << " drop(ttl1000/srcRet/maxTtl/wait)=" << scouts_dropped_ttl_gt_1000 << "/" << scouts_dropped_return_src << "/"
                     << scouts_dropped_max_ttl << "/" << scouts_dropped_wait
                     << " accept_hops[1..5,6+]=" << scout_accept_hop_hist[0] << "," << scout_accept_hop_hist[1] << ","
                     << scout_accept_hop_hist[2] << "," << scout_accept_hop_hist[3] << "," << scout_accept_hop_hist[4] << ","
                     << scout_accept_hop_hist[5]
                     << " chunks(start/recv)=" << chunks_started << "/" << chunks_received
                     << " key_events=" << keys_established_events
                     << "\n";

                // Also log which nodes are still below watermark buffered keys for each source.
                // This is a proxy for "nodes still waiting for watermark with every source".
                const int max_names_per_src = 10;
                for (int s : src_indices) {
                    vector<string> names;
                    names.reserve(max_names_per_src);
                    int missing = 0;
                    for (int v = 0; v < n; v++) {
                        if (v == s) continue;
                        const int have = buffered_keys[v][s];
                        if (have >= opts.watermark_sz) continue;
                        missing++;
                        if (static_cast<int>(names.size()) < max_names_per_src) {
                            names.push_back(graph.node_name(v));
                        }
                    }
                    cerr << "  [watermark<src=" << graph.node_name(s) << "] missing=" << missing;
                    if (!names.empty()) {
                        cerr << " e.g.";
                        for (const auto &nm : names) cerr << " " << nm;
                        if (missing > static_cast<int>(names.size())) cerr << " ...";
                    }
                    cerr << "\n";
                }

                wall_last_log = wall_now;
                processed_at_last_log = processed_events;
            }
        }

        if (ev.type == EventType::EmitScout) {
            const int s = ev.src_for_emit;
            if (s < 0 || s >= n) continue;
            if (!is_src[s]) continue;
            if (adj[s].empty()) continue;

            auto scout = make_shared<Scout>();
            scouts_emitted++;
            scout_counter++;
            scout->src = s;
            scout->hops = 0;
            scout->walk_nodes.clear();
            scout->walk_nodes.push_back(s);
            // IMPORTANT: For scouting, do NOT set RW target to the source.
            // Many RW variants have a "direct-to-visible-target" shortcut that would keep snapping back to `s`,
            // severely limiting exploration. Use a sentinel target (-1) so that shortcut never triggers.
            scout->token = make_base_token(opts.rw_variant, s, -1, derive_scout_seed(opts.seed, scout_counter), n);
            if (!scout->token) throw runtime_error("Unknown random walk variant: " + opts.rw_variant);

            int next = scout->token->choose_next_and_update(s, graph.neighbors(s));
            pq.push(Event{ev.time + kClassicLatencyS, EventType::ScoutArrive, -1, scout, nullptr, s, next, -1});

            const double dt = 1.0 / opts.scout_rate_per_s;
            schedule_emit_scout(ev.time + dt, s);
            continue;
        }

        if (ev.type == EventType::ScoutArrive) {
            auto scout = ev.scout;
            if (!scout) continue;
            const int receiver = ev.to;
            const int sender = ev.from;
            if (receiver < 0 || receiver >= n) continue;

            scout->hops += 1;
            scout->walk_nodes.push_back(receiver);
            if (scout->hops > 1000) {
                scouts_dropped_ttl_gt_1000++;
                continue;
            }

            // Loop-prevention: if it returns to its source, drop.
            if (receiver == scout->src && scout->hops > 1) {
                scouts_dropped_return_src++;
                continue;
            }

            // Observe waiting time of the traversed QKD link (queue length * chunk / SKR).
            (void)qkd.link_state(sender, receiver).observe_wait_s(ev.time);

            const int buffered = buffered_keys[receiver][scout->src];
            const double p = consume_probability(scout->hops, kMaxTtl, buffered, opts.watermark_sz);
            const bool accept = (scout->hops >= kMinTtl && scout->hops <= kMaxTtl && u01(rng) < p);

            if (accept) {
                scout->tgt = receiver;
                scout->raw_walk_vertices_at_accept = static_cast<int>(scout->walk_nodes.size());
                scout->hops_at_accept = scout->hops;
                scout->path = loop_erase_path(scout->walk_nodes);
                if (scout->path.size() < 2 || scout->path.front() != scout->src || scout->path.back() != scout->tgt) {
                    throw runtime_error("loop erasure produced invalid path");
                }

                // Target evaluates the path based on current per-link waiting times.
                double max_wait = 0.0;
                for (size_t i = 0; i + 1 < scout->path.size(); i++) {
                    const int a = scout->path[i];
                    const int b = scout->path[i + 1];
                    const double w = qkd.link_state(a, b).observe_wait_s(ev.time);
                    max_wait = max(max_wait, w);
                }
                if (max_wait > kDropIfAnyLinkWaitGtS) {
                    scouts_dropped_wait++;
                    continue; // drop scout at target
                }

                // Begin return: enqueue onto each link queue along the path (from t back to s).
                scouts_accepted++;
                {
                    const int hb = min(max(scout->hops_at_accept - 1, 0), 5);
                    scout_accept_hop_hist[static_cast<size_t>(hb)]++;
                }
                scout->hop_ready_time.assign(scout->path.size() - 1, 0.0);
                const int start_pos = static_cast<int>(scout->path.size()) - 1; // index of target node in path
                pq.push(Event{ev.time, EventType::ScoutReturnStep, -1, scout, nullptr, -1, -1, start_pos});
                continue;
            }

            if (scout->hops >= kMaxTtl) {
                scouts_dropped_max_ttl++;
                continue;
            }
            if (adj[receiver].empty()) continue;

            int next = scout->token->choose_next_and_update(receiver, adj[receiver]);
            pq.push(Event{ev.time + kClassicLatencyS, EventType::ScoutArrive, -1, scout, nullptr, receiver, next, -1});
            continue;
        }

        if (ev.type == EventType::ScoutReturnStep) {
            auto scout = ev.scout;
            if (!scout) continue;
            if (scout->tgt < 0) continue;
            if (scout->path.size() < 2) continue;

            int pos = ev.return_pos;
            if (pos <= 0) {
                // Scout has reached source, compute when to send chunk.
                const double now = ev.time;
                double send_time = now;
                // For hop i (path[i]->path[i+1]), chunk reaches node path[i] at send_time + i*latency.
                for (size_t i = 0; i + 1 < scout->path.size(); i++) {
                    const double ready = scout->hop_ready_time[i];
                    const double candidate_send = ready - static_cast<double>(i) * kClassicLatencyS;
                    send_time = max(send_time, candidate_send);
                }

                auto chunk = make_shared<Chunk>();
                chunk->src = scout->src;
                chunk->tgt = scout->tgt;
                chunk->path = scout->path;
                chunk->pos = 0;
                chunk->raw_walk_vertices_at_accept = scout->raw_walk_vertices_at_accept;
                chunk->hops_at_accept = scout->hops_at_accept;
                pq.push(Event{send_time, EventType::StartChunk, -1, nullptr, chunk, -1, -1, -1});
                continue;
            }

            // Enqueue the scout on the link (path[pos-1] <-> path[pos]) to reserve one chunk worth of key.
            const int a = scout->path[pos - 1];
            const int b = scout->path[pos];
            const double ready_time = qkd.link_state(a, b).enqueue_and_get_ready_time(ev.time);
            // Store by forward-hop index (pos-1).
            scout->hop_ready_time[pos - 1] = ready_time;

            pq.push(Event{ev.time + kClassicLatencyS, EventType::ScoutReturnStep, -1, scout, nullptr, -1, -1, pos - 1});
            continue;
        }

        if (ev.type == EventType::StartChunk) {
            auto chunk = ev.chunk;
            if (!chunk) continue;
            if (chunk->path.size() < 2) continue;
            chunks_started++;

            const int from = chunk->path[0];
            const int to = chunk->path[1];
            pq.push(Event{ev.time + kClassicLatencyS, EventType::ChunkArriveHop, -1, nullptr, chunk, from, to, -1});
            continue;
        }

        if (ev.type == EventType::ChunkArriveHop) {
            auto chunk = ev.chunk;
            if (!chunk) continue;

            const int receiver = ev.to;
            (void)receiver;
            chunk->pos += 1;

            if (chunk->pos >= static_cast<int>(chunk->path.size()) - 1) {
                // Arrived at target.
                chunks_received++;
                vector<string> path_names;
                path_names.reserve(chunk->path.size());
                for (int idx : chunk->path) path_names.push_back(graph.node_name(idx));
                reported.push_back(ReportedRecvChunkEvent{
                    ev.time, graph.node_name(chunk->src), graph.node_name(chunk->tgt), std::move(path_names)
                });

                int &cnt = block_recv_count[chunk->tgt][chunk->src];
                cnt += 1;
                block_paths[chunk->tgt][chunk->src].push_back(BlockPathEntry{
                    chunk->path, chunk->raw_walk_vertices_at_accept, chunk->hops_at_accept});
                if (cnt >= opts.block_chunks) {
                    cnt = 0;
                    // Adversary model (for now): cartel size m=1, chosen optimally per (src,tgt)
                    // as the intermediate node(s) that cover the most chunk paths in this block window.
                    const auto &paths = block_paths[chunk->tgt][chunk->src];
                    const size_t W = paths.size();
                    const size_t words = (W + 63) / 64;

                    // Diagnostics: path diversity and first-hop distribution from src.
                    struct VecHash {
                        size_t operator()(const vector<int> &v) const noexcept {
                            size_t h = 0;
                            for (int x : v) {
                                h ^= std::hash<int>{}(x) + 0x9e3779b97f4a7c15ull + (h << 6) + (h >> 2);
                            }
                            return h;
                        }
                    };
                    unordered_set<vector<int>, VecHash> unique_paths;
                    unique_paths.reserve(paths.size() * 2 + 1);
                    unordered_map<int, int> first_hop_count;
                    first_hop_count.reserve(32);
                    for (const auto &e : paths) {
                        unique_paths.insert(e.path);
                        if (e.path.size() >= 2) first_hop_count[e.path[1]] += 1;
                    }

                    // node -> bitset of which path indices contain it
                    unordered_map<int, vector<uint64_t>> seen_bits;
                    seen_bits.reserve(256);
                    for (size_t pi = 0; pi < paths.size(); pi++) {
                        const auto &e = paths[pi];
                        const auto &p = e.path;
                        if (p.size() < 2) continue;
                        const size_t wi = pi / 64;
                        const uint64_t bit = 1ull << (pi % 64);
                        for (size_t i = 1; i + 1 < p.size(); i++) { // exclude src and tgt
                            const int mid = p[i];
                            if (mid == chunk->src || mid == chunk->tgt) continue;
                            auto &bs = seen_bits[mid];
                            if (bs.empty()) bs.assign(words, 0ull);
                            bs[wi] |= bit;
                        }
                    }

                    auto popcount_words = [&](const vector<uint64_t> &bs) -> int {
                        int c = 0;
                        for (uint64_t w : bs) c += __builtin_popcountll(w);
                        return c;
                    };

                    int max_seen_by_cartel = 0;
                    vector<int> best_nodes;
                    if (opts.cartel_size == 0) {
                        // No adversary: cartel sees nothing.
                        max_seen_by_cartel = 0;
                        best_nodes.clear();
                    } else if (opts.cartel_size == 1) {
                        int best = -1;
                        for (const auto &kv : seen_bits) {
                            const int node = kv.first;
                            const int c = popcount_words(kv.second);
                            if (c > max_seen_by_cartel) {
                                max_seen_by_cartel = c;
                                best = node;
                            }
                        }
                        if (best >= 0) best_nodes = {best};
                    } else {
                        // cartel_size == 2: choose pair maximizing popcount(OR(bitset_i, bitset_j)).
                        vector<int> nodes;
                        nodes.reserve(seen_bits.size());
                        for (const auto &kv : seen_bits) nodes.push_back(kv.first);

                        int best_a = -1, best_b = -1;
                        for (size_t i = 0; i < nodes.size(); i++) {
                            const int a = nodes[i];
                            const auto &A = seen_bits[a];
                            // allow pair with itself only if only one node exists; otherwise it doesn't improve union.
                            for (size_t j = i; j < nodes.size(); j++) {
                                const int b = nodes[j];
                                const auto &B = seen_bits[b];
                                int c = 0;
                                for (size_t w = 0; w < words; w++) {
                                    c += __builtin_popcountll(A[w] | B[w]);
                                }
                                if (c > max_seen_by_cartel) {
                                    max_seen_by_cartel = c;
                                    best_a = a;
                                    best_b = b;
                                }
                            }
                        }
                        if (best_a >= 0) {
                            best_nodes = {best_a, best_b};
                            if (best_nodes.size() == 2 && best_nodes[0] == best_nodes[1]) best_nodes.resize(1);
                        }
                    }

                    const int h = static_cast<int>(opts.block_chunks) - max_seen_by_cartel;
                    const int extracted_keys = (h > 0) ? min(opts.max_block_keys, h) : 0;

                    reported.push_back(ReportedKeyEstablEvent{
                        ev.time, graph.node_name(chunk->src), graph.node_name(chunk->tgt), extracted_keys
                    });
                    established_keys[chunk->tgt][chunk->src] += extracted_keys;
                    buffered_keys[chunk->tgt][chunk->src] += extracted_keys;
                    keys_established_events++;

                    int sc_h_min = 0, sc_h_max = 0, sc_w_min = 0, sc_w_max = 0, sc_e_min = 0, sc_e_max = 0;
                    long long sc_h_sum = 0, sc_w_sum = 0, sc_e_sum = 0;
                    array<int, 6> block_accept_hist{};
                    {
                        bool sc_first = true;
                        for (const auto &e : paths) {
                            const int ha = e.scout_hops_at_accept;
                            const int wv = e.scout_raw_walk_vertices;
                            const int ev = static_cast<int>(e.path.size());
                            if (sc_first) {
                                sc_h_min = sc_h_max = ha;
                                sc_w_min = sc_w_max = wv;
                                sc_e_min = sc_e_max = ev;
                                sc_first = false;
                            } else {
                                sc_h_min = min(sc_h_min, ha);
                                sc_h_max = max(sc_h_max, ha);
                                sc_w_min = min(sc_w_min, wv);
                                sc_w_max = max(sc_w_max, wv);
                                sc_e_min = min(sc_e_min, ev);
                                sc_e_max = max(sc_e_max, ev);
                            }
                            sc_h_sum += ha;
                            sc_w_sum += wv;
                            sc_e_sum += ev;
                            const int hb = min(max(ha - 1, 0), 5);
                            block_accept_hist[static_cast<size_t>(hb)]++;
                        }
                    }
                    const double sc_h_avg = W ? static_cast<double>(sc_h_sum) / static_cast<double>(W) : 0.0;
                    const double sc_w_avg = W ? static_cast<double>(sc_w_sum) / static_cast<double>(W) : 0.0;
                    const double sc_e_avg = W ? static_cast<double>(sc_e_sum) / static_cast<double>(W) : 0.0;

                    if (opts.verbose) {
                        auto print_path_compact = [&](const vector<int> &p) -> void {
                            const int max_nodes = 18;
                            cerr << "[";
                            if ((int)p.size() <= max_nodes) {
                                for (size_t i = 0; i < p.size(); i++) {
                                    if (i) cerr << " ";
                                    cerr << graph.node_name(p[i]);
                                }
                            } else {
                                for (int i = 0; i < max_nodes / 2; i++) {
                                    if (i) cerr << " ";
                                    cerr << graph.node_name(p[i]);
                                }
                                cerr << " ...";
                                for (size_t i = p.size() - (max_nodes / 2); i < p.size(); i++) {
                                    cerr << " " << graph.node_name(p[i]);
                                }
                            }
                            cerr << "]";
                        };

                        cerr.setf(ios::fixed);
                        cerr.precision(2);
                        cerr << "  [block] sim=" << ev.time
                             << " src=" << graph.node_name(chunk->src)
                             << " tgt=" << graph.node_name(chunk->tgt)
                             << " cartel_size=" << opts.cartel_size
                             << " uniq_paths=" << unique_paths.size()
                             << " max_seen=" << max_seen_by_cartel
                             << " h=" << h
                             << " keys=" << extracted_keys
                             << " accept_hops(min/avg/max)=" << sc_h_min << "/" << sc_h_avg << "/" << sc_h_max
                             << " hist[1..6+]=" << block_accept_hist[0] << "," << block_accept_hist[1] << ","
                             << block_accept_hist[2] << "," << block_accept_hist[3] << "," << block_accept_hist[4] << ","
                             << block_accept_hist[5]
                             << " walk_v(min/avg/max)=" << sc_w_min << "/" << sc_w_avg << "/" << sc_w_max
                             << " erased_v(min/avg/max)=" << sc_e_min << "/" << sc_e_avg << "/" << sc_e_max;
                        if (!best_nodes.empty()) {
                            cerr << " cartel_nodes=";
                            for (size_t i = 0; i < best_nodes.size(); i++) {
                                if (i) cerr << ",";
                                cerr << graph.node_name(best_nodes[i]);
                            }
                        }
                        // First-hop distribution (top 5).
                        {
                            vector<pair<int, int>> fh;
                            fh.reserve(first_hop_count.size());
                            for (const auto &kv : first_hop_count) fh.push_back({kv.first, kv.second});
                            sort(fh.begin(), fh.end(), [](const auto &a, const auto &b) {
                                if (a.second != b.second) return a.second > b.second;
                                return a.first < b.first;
                            });
                            cerr << " first_hops=";
                            const int show = min<int>(5, fh.size());
                            for (int i = 0; i < show; i++) {
                                if (i) cerr << ",";
                                cerr << graph.node_name(fh[i].first) << ":" << fh[i].second;
                            }
                            if ((int)fh.size() > show) cerr << ",...";
                        }
                        // Intermediate nodes (top 5 by number of paths they appear in).
                        {
                            vector<pair<int, int>> top_mid;
                            top_mid.reserve(seen_bits.size());
                            for (const auto &kv : seen_bits) {
                                int c = 0;
                                for (uint64_t w : kv.second) c += __builtin_popcountll(w);
                                top_mid.push_back({kv.first, c});
                            }
                            sort(top_mid.begin(), top_mid.end(), [](const auto &a, const auto &b) {
                                if (a.second != b.second) return a.second > b.second;
                                return a.first < b.first;
                            });
                            cerr << " top_mid=";
                            const int show = min<int>(5, top_mid.size());
                            for (int i = 0; i < show; i++) {
                                if (i) cerr << ",";
                                cerr << graph.node_name(top_mid[i].first) << ":" << top_mid[i].second;
                            }
                            if ((int)top_mid.size() > show) cerr << ",...";
                        }
                        // Representative path(s) when diversity is small.
                        if (unique_paths.size() <= 2) {
                            int shown = 0;
                            for (const auto &p : unique_paths) {
                                cerr << " path" << (shown + 1) << "=";
                                print_path_compact(p);
                                shown++;
                                if (shown >= 2) break;
                            }
                        }

                        // If cartel dominates the whole window, check whether a cartel-avoiding path exists in the graph.
                        if (!best_nodes.empty() && max_seen_by_cartel >= opts.block_chunks) {
                            cerr << " avoid_cartel_path=" << (exists_path_avoiding_nodes(graph, chunk->src, chunk->tgt, best_nodes) ? 1 : 0);
                        }
                        cerr << "\n";
                    }
                    block_paths[chunk->tgt][chunk->src].clear();
                    if (early_stop_satisfied()) break;
                }
                continue;
            }

            const int from = chunk->path[chunk->pos];
            const int to = chunk->path[chunk->pos + 1];
            pq.push(Event{ev.time + kClassicLatencyS, EventType::ChunkArriveHop, -1, nullptr, chunk, from, to, -1});
            continue;
        }
    }

    stable_sort(reported.begin(), reported.end(), [](const ReportedEvent &a, const ReportedEvent &b) {
        const double ta = visit([](auto &&e) { return e.time; }, a);
        const double tb = visit([](auto &&e) { return e.time; }, b);
        return ta < tb;
    });

    return SimulationOutput{std::move(reported)};
}

static void print_output(const Options &opts, const SimulationOutput &outp, ostream &out) {
    auto join_src = [&]() -> string {
        string s;
        for (size_t i = 0; i < opts.src_nodes.size(); ++i) {
            if (i) s += ',';
            s += opts.src_nodes[i];
        }
        return s;
    };

    out << "src_nodes: " << join_src() << "\n";
    out << "rw_variant: " << opts.rw_variant << "\n";
    out << "duration_s: " << opts.duration_s << "\n";
    out << "scout_rate_per_s: " << opts.scout_rate_per_s << "\n";
    if (!opts.delete_nodes.empty()) {
        out << "delete_nodes: ";
        for (size_t i = 0; i < opts.delete_nodes.size(); i++) {
            if (i) out << ",";
            out << opts.delete_nodes[i];
        }
        out << "\n";
    } else {
        out << "delete_nodes: " << "\n";
    }
    out << "block_chunks: " << opts.block_chunks << "\n";
    out << "max_block_keys: " << opts.max_block_keys << "\n";
    out << "cartel_size: " << opts.cartel_size << "\n";
    out << "watermark_sz: " << opts.watermark_sz << "\n";
    out << "min_keys_per_pair: " << opts.min_keys_per_pair << "\n";
    out << "seed: " << opts.seed << "\n";
    out << "verbose: " << (opts.verbose ? 1 : 0) << "\n";
    out << "event_count: " << outp.reported.size() << "\n";
    for (const auto &ev : outp.reported) print_event_line(ev, out);
    out << "\n";
}

int main(int argc, char **argv) {
    try {
        Options opts = parse_args(argc, argv);
        Graph base_graph = opts.edges_csv.empty() ? Graph(cin) : Graph(opts.edges_csv);
        for (const string &name : opts.src_nodes) base_graph.node_index(name);
        for (const string &nm : opts.delete_nodes) {
            // Only validate if node exists; otherwise ignore silently.
            // This makes "eyeballing deletions" convenient.
            try { (void)base_graph.node_index(nm); } catch (...) {}
        }
        for (const string &name : opts.src_nodes) {
            for (const string &del : opts.delete_nodes) {
                if (trim_copy(name) == trim_copy(del)) {
                    throw runtime_error("Cannot delete a source node: " + name);
                }
            }
        }

        Graph graph = build_filtered_graph(base_graph, opts.delete_nodes);
        // Ensure sources still exist after filtering.
        for (const string &name : opts.src_nodes) graph.node_index(name);

        SimulationOutput outp = run_simulation(opts, graph);
        print_output(opts, outp, cout);
        return 0;
    } catch (const exception &e) {
        cerr << e.what() << "\n";
        return 1;
    }
}
