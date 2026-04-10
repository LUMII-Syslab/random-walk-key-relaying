#include <cctype>
#include <iostream>
#include <queue>
#include <random>
#include <sstream>
#include <string>
#include <type_traits>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>
#include <memory>
#include <fstream>

#include "graph.hpp"
#include "walk.hpp"
using namespace std;

static constexpr double kClassicLatencyS = 0.005; // 5 ms
static constexpr int kChunkBits = 256;
static constexpr double kQkdSkrBitsPerS = 1000.0;
static constexpr int kLinkBuffSzBits = 2'000'000'000; // effectively unlimited
static constexpr int kMinTtl = 1;
static constexpr int kMaxTtl = 100;

/**
 * Mirrors helpers/compute.py ProactiveRecvChunkEvent / ProactiveKeyEstablishedEvent.
 */
struct ReportedRecvChunkEvent {
    double time = 0.0;
    string src;
    string tgt;
    vector<string> path;
};

struct ReportedKeyEstablEvent {
    double time = 0.0;
    string src;
    string tgt;
    int key_count = 0;
};

using ReportedEvent = variant<ReportedRecvChunkEvent, ReportedKeyEstablEvent>;

struct Packet {
    int source = -1;      // originator node (A)
    int prev_hop = -1;    // last sender to current receiver
    int hops = 0;         // hop index of current receiver (1..)
    unique_ptr<RwToken> token;
    vector<int> path;     // node indices (excluding source), for reporting
};

enum class InternalEventType {
    OtpAvailable,
    ChunkReceived,
    AckResponse,
};

struct InternalEvent {
    double time = 0.0;
    InternalEventType type = InternalEventType::OtpAvailable;
    int from = -1; // sender for OtpAvailable, receiver for AckResponse
    int to = -1;   // next-hop receiver for OtpAvailable, sender for AckResponse
    shared_ptr<Packet> pkt;
};

struct InternalEventGreater {
    bool operator()(const InternalEvent &a, const InternalEvent &b) const {
        return a.time > b.time;
    }
};

/**
 * Mirrors helpers/compute.py ProactiveSimParams (graph via stdin or --edges-csv).
 * Fixed assumptions (docstring there): chunk 256 bits, SKR 1000 b/s, unlimited buffers,
 * latency 5 ms, TTL 1–100 — not represented as CLI flags yet.
 */
struct Options {
    vector<string> src_nodes;
    string rw_variant;
    double duration_s = 0.0;
    int sieve_table_sz = 32;
    int watermark_sz = 16;
    string edges_csv = "";
    int relay_buff_sz = 100; // fifo relay buffer size
    string ignore_events = "";     // comma-separated list of event kinds to suppress (e.g. "recv_chunk,key_establ")
    string ignore_events_csv = ""; // legacy: optional path to ignore-rules file (still supported)
};

void print_usage(const char *prog_name);
Options parse_args(int argc, char **argv);
struct SimulationOutput {
    vector<ReportedEvent> reported;
    double watermark_time = 0.0;
};
static void print_proactive_output(const Options &opts, const SimulationOutput &outp, ostream &out);

struct IgnoreRule {
    string kind; // "recv_chunk" or "key_establ"
    string src;  // optional, "*" or empty means wildcard
    string tgt;  // optional, "*" or empty means wildcard
};

static string trim_copy(string s) {
    while (!s.empty() && isspace(static_cast<unsigned char>(s.back()))) s.pop_back();
    size_t i = 0;
    while (i < s.size() && isspace(static_cast<unsigned char>(s[i]))) i++;
    return s.substr(i);
}

static vector<string> split_csv_line_simple(const string &line) {
    // Minimal CSV: comma-separated, no quotes/escapes (good enough for node names).
    vector<string> out;
    string cur;
    for (char ch : line) {
        if (ch == ',') {
            out.push_back(trim_copy(cur));
            cur.clear();
        } else {
            cur.push_back(ch);
        }
    }
    out.push_back(trim_copy(cur));
    return out;
}

static vector<string> parse_ignore_kinds_inline(const string &csv) {
    vector<string> parts = split_csv_line_simple(csv);
    vector<string> out;
    out.reserve(parts.size());
    for (string &p : parts) {
        p = trim_copy(p);
        if (p.empty()) continue;
        out.push_back(p);
    }
    return out;
}

static vector<IgnoreRule> read_ignore_rules(const string &path) {
    if (path.empty()) return {};
    ifstream in(path);
    if (!in.is_open()) {
        throw runtime_error("Cannot open ignore-events CSV: " + path);
    }
    vector<IgnoreRule> rules;
    string line;
    while (getline(in, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        line = trim_copy(line);
        if (line.empty()) continue;
        if (!line.empty() && line[0] == '#') continue;
        vector<string> parts = split_csv_line_simple(line);
        if (parts.empty()) continue;
        IgnoreRule r;
        r.kind = parts[0];
        r.src = (parts.size() >= 2 ? parts[1] : "");
        r.tgt = (parts.size() >= 3 ? parts[2] : "");
        if (r.kind.empty()) continue;
        rules.push_back(std::move(r));
    }
    return rules;
}

static bool rule_matches_field(const string &rule, const string &value) {
    if (rule.empty() || rule == "*") return true;
    return rule == value;
}

static bool should_ignore_event(const vector<IgnoreRule> &rules, const ReportedEvent &ev) {
    return visit([&](auto &&e) -> bool {
        using T = decay_t<decltype(e)>;
        const string kind = is_same_v<T, ReportedKeyEstablEvent> ? "key_establ" : "recv_chunk";
        for (const auto &r : rules) {
            if (r.kind != kind) continue;
            if (!rule_matches_field(r.src, e.src)) continue;
            if (!rule_matches_field(r.tgt, e.tgt)) continue;
            return true;
        }
        return false;
    }, ev);
}

unique_ptr<RwToken> make_base_token(const string &rw_variant, int src_idx, int tgt_idx, int seed, int node_count) {
    if (rw_variant == "R") return make_unique<RToken>(src_idx, tgt_idx, seed);
    if (rw_variant == "NB") return make_unique<NbToken>(src_idx, tgt_idx, seed);
    if (rw_variant == "LRV") return make_unique<LrvToken>(src_idx, tgt_idx, seed);
    if (rw_variant == "NC") return make_unique<NcToken>(src_idx, tgt_idx, seed, node_count);
    if (rw_variant == "HS") return make_unique<HsToken>(src_idx, tgt_idx, seed);
    return nullptr;
}

int get_rng_seed() {
    static int seed_offset = 0;
    seed_offset++;
    return seed_offset;
}

static double consume_probability(int hops, int max_ttl, int buffered_keys_for_src, int watermark_sz) {
    if (watermark_sz <= 0) return 1.0;
    const double b = min(1.0, static_cast<double>(buffered_keys_for_src) / static_cast<double>(watermark_sz));
    const double t_remaining = static_cast<double>(max_ttl - hops) / static_cast<double>(max_ttl);
    const double p = 1.0 - b * t_remaining;
    if (p < 0.0) return 0.0;
    if (p > 1.0) return 1.0;
    return p;
}

SimulationOutput run_simulation(const Options &opts, const Graph &graph) {
    QkdNetwork qkd_network(graph);

    priority_queue<InternalEvent, vector<InternalEvent>, InternalEventGreater> event_queue;
    mt19937 rng(1234567);
    uniform_real_distribution<double> u01(0.0, 1.0);
    vector<IgnoreRule> ignore_rules = read_ignore_rules(opts.ignore_events_csv);
    for (const string &k : parse_ignore_kinds_inline(opts.ignore_events)) {
        IgnoreRule r;
        r.kind = k;
        r.src = "*";
        r.tgt = "*";
        ignore_rules.push_back(std::move(r));
    }

    const auto &adj = graph.adj_list();
    const int node_count = graph.node_count();

    // Per-node send window: how many in-flight chunks can be outstanding awaiting ACK.
    vector<int> in_flight_free(node_count, opts.relay_buff_sz);

    // Per-node, per-source FIFO occupancy (for drop decision at receiver).
    vector<unordered_map<int, int>> per_source_fifo_used(node_count);

    // Per-node, per-source "relayed key buffer" size approximation for b in p=1-b*t_remaining.
    vector<unordered_map<int, int>> rt_size(node_count);

    // Batch of consumed chunk histories for (tgt, src) to trigger key establishment.
    // We only need counts/histories at this stage (not raw chunks).
    struct HistItem { vector<int> path; };
    vector<unordered_map<int, vector<HistItem>>> consumed_hist(node_count);

    vector<int> established_keys_per_src(node_count, 0);
    vector<char> is_src(node_count, 0);
    for (const string &name : opts.src_nodes) {
        is_src[graph.node_index(name)] = 1;
    }
    double watermark_time = 0.0;
    bool watermark_reached = false;

    auto schedule_new_chunk_from_src = [&](double now, int src_idx) -> void {
        if (!is_src[src_idx]) return;
        if (adj[src_idx].empty()) return;
        if (in_flight_free[src_idx] <= 0) return;

        in_flight_free[src_idx]--;

        auto pkt = make_shared<Packet>();
        pkt->source = src_idx;
        pkt->prev_hop = src_idx;
        pkt->hops = 0;
        pkt->token = make_base_token(opts.rw_variant, src_idx, src_idx, get_rng_seed(), node_count);
        if (!pkt->token) throw runtime_error("Unknown random walk variant: " + opts.rw_variant);

        RwToken::WalkNodeState node_state;
        node_state.node_idx = src_idx;
        int next = pkt->token->choose_next_and_update(node_state, graph.neighbors(src_idx));

        // Reserve OTP on (src -> next) and schedule availability.
        const double wait = qkd_network.link_state(src_idx, next).reserve(
            now, kChunkBits, kLinkBuffSzBits, kQkdSkrBitsPerS
        );
        event_queue.push(InternalEvent{now + wait, InternalEventType::OtpAvailable, src_idx, next, pkt});
    };

    // Bootstrap: fill each source's send window initially.
    for (const string &src_name : opts.src_nodes) {
        const int src_idx = graph.node_index(src_name);
        for (int i = 0; i < opts.relay_buff_sz; i++) {
            schedule_new_chunk_from_src(0.0, src_idx);
        }
    }

    vector<ReportedEvent> reported;
    // Main event loop.
    while (!event_queue.empty()) {
        InternalEvent ev = event_queue.top();
        event_queue.pop();
        if (ev.time > opts.duration_s) break;

        if (ev.type == InternalEventType::OtpAvailable) {
            // After 5 ms classical latency, receiver sees the chunk.
            event_queue.push(InternalEvent{ev.time + kClassicLatencyS, InternalEventType::ChunkReceived, ev.from, ev.to, ev.pkt});
            continue;
        }

        if (ev.type == InternalEventType::ChunkReceived) {
            auto &pkt = *ev.pkt;
            const int receiver = ev.to;
            const int sender = ev.from;
            pkt.prev_hop = sender;
            pkt.hops += 1;
            if (pkt.hops > 1000) throw runtime_error("Random walk exceeded 1000 steps");
            pkt.path.push_back(receiver);

            // Loop-prevention: if a chunk returns to its origin source, drop it.
            const bool returned_to_source = (receiver == pkt.source) && (pkt.hops > 1);

            // FIFO per-source relay buffer constraint at receiver.
            int &used = per_source_fifo_used[receiver][pkt.source];
            const bool drop = returned_to_source || (used >= opts.relay_buff_sz);
            if (!drop) {
                used++;
            }

            // Report recv_chunk at arrival (even if it will be dropped later, per your description B "receives").
            vector<string> path_names;
            path_names.reserve(pkt.path.size());
            for (int idx : pkt.path) path_names.push_back(graph.node_name(idx));
            {
                ReportedEvent rep = ReportedRecvChunkEvent{ev.time, graph.node_name(pkt.source), graph.node_name(receiver), std::move(path_names)};
                if (!should_ignore_event(ignore_rules, rep)) {
                    reported.push_back(std::move(rep));
                }
            }

            // Decide consume / forward / drop.
            bool consumed = false;
            if (!drop) {
                const int buffered = rt_size[receiver][pkt.source];
                const double p = consume_probability(pkt.hops, kMaxTtl, buffered, opts.watermark_sz);
                if (pkt.hops >= kMinTtl && pkt.hops <= kMaxTtl && u01(rng) < p) {
                    consumed = true;
                    rt_size[receiver][pkt.source] = buffered + 1;
                    consumed_hist[receiver][pkt.source].push_back(HistItem{pkt.path});

                    // When enough consumed chunks are collected, establish at least one 256-bit key (XOR is always possible).
                    if (static_cast<int>(consumed_hist[receiver][pkt.source].size()) >= opts.sieve_table_sz) {
                        consumed_hist[receiver][pkt.source].clear();
                        {
                            ReportedEvent rep = ReportedKeyEstablEvent{ev.time, graph.node_name(pkt.source), graph.node_name(receiver), 1};
                            if (!should_ignore_event(ignore_rules, rep)) {
                                reported.push_back(std::move(rep));
                            }
                        }
                        established_keys_per_src[pkt.source] += 1;
                        if (!watermark_reached) {
                            bool all_ok = true;
                            for (const string &src_name : opts.src_nodes) {
                                const int sidx = graph.node_index(src_name);
                                if (established_keys_per_src[sidx] < opts.watermark_sz) {
                                    all_ok = false;
                                    break;
                                }
                            }
                            if (all_ok) {
                                watermark_reached = true;
                                watermark_time = ev.time;
                            }
                        }
                    }
                }
            }

            if (!drop && !consumed) {
                // Forward (random walk step).
                if (adj[receiver].empty()) {
                    // nowhere to go, treat as drop
                } else {
                    RwToken::WalkNodeState node_state;
                    node_state.node_idx = receiver;
                    int next = pkt.token->choose_next_and_update(node_state, adj[receiver]);
                    const double wait = qkd_network.link_state(receiver, next).reserve(
                        ev.time, kChunkBits, kLinkBuffSzBits, kQkdSkrBitsPerS
                    );
                    event_queue.push(InternalEvent{ev.time + wait, InternalEventType::OtpAvailable, receiver, next, ev.pkt});
                }
            }

            // Receiver buffer slot is freed after processing (consume/drop/forward decision is local).
            if (!drop) {
                used--;
                if (used < 0) throw runtime_error("per-source fifo accounting underflow");
            }

            // ACK always sent back after additional 5ms; frees one in-flight slot at sender.
            event_queue.push(InternalEvent{ev.time + kClassicLatencyS, InternalEventType::AckResponse, receiver, sender, ev.pkt});
            continue;
        }

        if (ev.type == InternalEventType::AckResponse) {
            const int sender = ev.to; // original sender of the chunk hop
            if (sender < 0 || sender >= node_count) continue;
            if (is_src[sender]) {
                in_flight_free[sender]++;
                if (in_flight_free[sender] > opts.relay_buff_sz) {
                    throw runtime_error("in_flight buffer accounting overflow");
                }
                // Now that one slot is freed, issue a new chunk if this is a configured source.
                schedule_new_chunk_from_src(ev.time, sender);
            }
            continue;
        }
    }

    // Sort by time to ensure monotone output.
    stable_sort(reported.begin(), reported.end(), [](const ReportedEvent &a, const ReportedEvent &b) {
        auto ta = visit([](auto &&e) { return e.time; }, a);
        auto tb = visit([](auto &&e) { return e.time; }, b);
        return ta < tb;
    });

    SimulationOutput outp;
    outp.reported = std::move(reported);
    outp.watermark_time = watermark_time;
    return outp;
}


static void print_event_line(const ReportedEvent &ev, ostream &out) {
    visit(
        [&](auto &&e) {
            using T = decay_t<decltype(e)>;
            if constexpr (is_same_v<T, ReportedKeyEstablEvent>) {
                out << "key_establ " << e.time << " " << e.src << " " << e.tgt << " " << e.key_count << endl;
            } else {
                out << "recv_chunk " << e.time << " " << e.src << " " << e.tgt;
                for (const string &hop : e.path) {
                    out << " " << hop;
                }
                out << endl;
            }
        },
        ev);
}

static void print_proactive_output(const Options &opts, const SimulationOutput &outp, ostream &out) {
    auto join_src = [&]() -> string {
        string s;
        for (size_t i = 0; i < opts.src_nodes.size(); ++i) {
            if (i) s += ',';
            s += opts.src_nodes[i];
        }
        return s;
    };

    out << "src_nodes: " << join_src() << endl;
    out << "rw_variant: " << opts.rw_variant << endl;
    out << "duration_s: " << opts.duration_s << endl;
    out << "sieve_table_sz: " << opts.sieve_table_sz << endl;
    out << "watermark_sz: " << opts.watermark_sz << endl;
    out << "watermark_time: " << outp.watermark_time << endl;
    out << "event_count: " << outp.reported.size() << endl;
    for (const ReportedEvent &ev : outp.reported) {
        print_event_line(ev, out);
    }
    out << endl;
}

int main(int argc, char **argv) {
    try {
        Options opts = parse_args(argc, argv);
        Graph graph = opts.edges_csv.empty() ? Graph(cin) : Graph(opts.edges_csv);
        for (const string &name : opts.src_nodes) {
            graph.node_index(name);
        }
        SimulationOutput outp = run_simulation(opts, graph);
        print_proactive_output(opts, outp, cout);
        return 0;
    } catch (const exception &e) {
        cerr << e.what() << endl;
        return 1;
    }
}

static string trim(string s) {
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
        part = trim(part);
        if (!part.empty()) out.push_back(part);
    }
    return out;
}

void print_usage(const char *prog_name) {
    cerr << "Usage: " << prog_name
         << " (--src-nodes|-S) <n1,n2,...> (--rw-variant|-w) <name> "
            "(--duration-s|-d) <seconds> "
            "[--sieve-table-sz <int>] [--watermark-sz <int>] "
            "[(--edges-csv|-e) <path>] [--ignore-events <csv>] [--ignore-events-csv <path>]" << endl;
}

static bool valid_rw_variant(const string &w) {
    return w == "R" || w == "NB" || w == "LRV" || w == "NC" || w == "HS";
}

Options parse_args(int argc, char **argv) {
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
            string raw = require_value(i, flag, has_inline, inline_value);
            opts.src_nodes = parse_src_nodes_csv(raw);
            have_src_nodes = true;
        } else if (flag == "--rw-variant" || flag == "-w") {
            opts.rw_variant = require_value(i, flag, has_inline, inline_value);
            have_rw = true;
        } else if (flag == "--duration-s" || flag == "-d") {
            opts.duration_s = stod(require_value(i, flag, has_inline, inline_value));
            have_duration = true;
        } else if (flag == "--sieve-table-sz") {
            opts.sieve_table_sz = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--watermark-sz") {
            opts.watermark_sz = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--edges-csv" || flag == "-e") {
            opts.edges_csv = require_value(i, flag, has_inline, inline_value);
        } else if (flag == "--ignore-events") {
            opts.ignore_events = require_value(i, flag, has_inline, inline_value);
        } else if (flag == "--ignore-events-csv") {
            opts.ignore_events_csv = require_value(i, flag, has_inline, inline_value);
        } else {
            fail("Unknown argument: " + string(arg));
        }
    }

    if (!have_src_nodes || opts.src_nodes.empty()) {
        fail("Non-empty --src-nodes is required (comma-separated node names)");
    }
    if (!have_rw || opts.rw_variant.empty()) {
        fail("--rw-variant is required");
    }
    if (!valid_rw_variant(opts.rw_variant)) {
        fail("Unknown random walk variant: " + opts.rw_variant);
    }
    if (!have_duration) {
        fail("--duration-s is required");
    }
    if (opts.duration_s <= 0.0) {
        fail("--duration-s must be > 0");
    }
    if (opts.sieve_table_sz <= 0) {
        fail("--sieve-table-sz must be > 0");
    }
    if (opts.watermark_sz <= 0) {
        fail("--watermark-sz must be > 0");
    }
    return opts;
}
