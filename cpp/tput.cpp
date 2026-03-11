#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <queue>
#include <string_view>
#include <vector>
#include "walk.hpp"
#include "utils.hpp"

using namespace std;

struct Options {
    string src_node = "";
    string tgt_node = "";
    string rw_variant = "LRV";
    string edges_csv = "";
    bool print_arrival_times = false;

    int chunk_size_bits = 256;
    int link_buff_sz_bits = 100000;
    double qkd_skr_bits_per_s = 1000.0;
    double latency_s = 0.05;
    double sim_duration_s = 1000.0;
    int relay_buffer_sz_chunks = 100000;
};

struct TputStats {
    int mean_tput_bits = 0;
    int emitted_chunks = 0;
    vector<double> arrival_times;

    void print(ostream &out, bool print_arrival_times) const {
        out << "mean_tput_bits: " << mean_tput_bits << endl;
        out << "emitted_chunks: " << emitted_chunks << endl;
        if (print_arrival_times) {
            out << "arrival_times: [";
            for (size_t i = 0; i < arrival_times.size(); i++) {
                if (i > 0) out << ",";
                out << fixed << setprecision(6) << arrival_times[i];
            }
            out << "]" << endl;
        }
    }
};

struct LinkState {
    double bit_balance = 0.0;
    double last_request = 0.0;

    double reserve(
        double current_time,
        int necessary_bits,
        int link_buff_sz_bits,
        double qkd_skr_bits_per_s
    ) {
        if (necessary_bits > link_buff_sz_bits) {
            throw runtime_error("chunk_size_bits > link_buff_sz_bits");
        }
        if (current_time < last_request) {
            throw runtime_error("current_time < last_request");
        }

        const double dt = current_time - last_request;
        bit_balance = min(static_cast<double>(link_buff_sz_bits), bit_balance + dt * qkd_skr_bits_per_s);
        const double waiting = max(0.0, (necessary_bits - bit_balance) / qkd_skr_bits_per_s);
        last_request = current_time;
        bit_balance -= necessary_bits;
        return waiting;
    }
};

struct EdgeKey {
    int u = -1;
    int v = -1;

    EdgeKey() = default;
    EdgeKey(int a, int b) {
        u = min(a, b);
        v = max(a, b);
    }
};

bool operator<(const EdgeKey &a, const EdgeKey &b) {
    if (a.u != b.u) return a.u < b.u;
    return a.v < b.v;
}

enum class EventType : uint8_t {
    OTP_AVAILABLE = 0,
    POLLED_BUFFER = 1,
    SLOT_ACQUIRED = 2,
    KEY_ARRIVED = 3,
};

struct Packet {
    int source = -1;
    int target = -1;
    unique_ptr<RwToken> token;
};

struct Event {
    double time = 0.0;
    EventType type;
    int from = -1;
    int at = -1;
    int next = -1;
    shared_ptr<Packet> pkt;
};

struct EventGreater {
    bool operator()(const Event &a, const Event &b) const {
        return a.time > b.time;
    }
};

struct RunResult {
    int arrived_chunks = 0;
    int emitted_chunks = 0;
    vector<double> arrival_times;
};

Options parse_args(int argc, char **argv);
void print_usage(const char *prog_name);
unique_ptr<RwToken> make_token(const Options &opts, int src_idx, int tgt_idx, int seed);
RunResult run_single_simulation(const vector<vector<int>> &adj, int src_idx, int tgt_idx, const Options &opts, int seed_offset);
TputStats compute_tput_stats(const RunResult &run, const Options &opts);

int main(int argc, char **argv) {
    Options opts = parse_args(argc, argv);
    Graph graph = opts.edges_csv.empty() ? Graph(cin) : Graph(opts.edges_csv);
    const auto &adj = graph.adj_list();

    int src_idx = graph.node_index(opts.src_node);
    int tgt_idx = graph.node_index(opts.tgt_node);

    RunResult run = run_single_simulation(adj, src_idx, tgt_idx, opts, 0);
    TputStats stats = compute_tput_stats(run, opts);
    stats.print(cout, opts.print_arrival_times);
    return 0;
}

void print_usage(const char *prog_name) {
    cerr << "Usage: " << prog_name
         << " (--src-node|-s) <node> (--tgt-node|-t) <node> "
            "[(--rw-variant|-w) <name>] "
            "[(--edges-csv|-e) <path>] "
            "[--chunk-size-bits <int>] [--link-buff-sz-bits <int>] "
            "[--qkd-skr-bits-per-s <float>] [--latency-s <float>] "
            "[--sim-duration-s <float>] [--relay-buffer-sz-chunks <int>] "
            "[--print-arrival-times]" << endl;
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
            if (inline_value.empty()) fail("Missing value for " + string(flag));
            return string(inline_value);
        }
        if (i + 1 >= argc) fail("Missing value for " + string(flag));
        return argv[++i];
    };

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

        if (flag == "--src-node" || flag == "-s") {
            opts.src_node = require_value(i, flag, has_inline, inline_value);
        } else if (flag == "--tgt-node" || flag == "-t") {
            opts.tgt_node = require_value(i, flag, has_inline, inline_value);
        } else if (flag == "--rw-variant" || flag == "-w") {
            opts.rw_variant = require_value(i, flag, has_inline, inline_value);
        } else if (flag == "--edges-csv" || flag == "-e") {
            opts.edges_csv = require_value(i, flag, has_inline, inline_value);
        } else if (flag == "--chunk-size-bits") {
            opts.chunk_size_bits = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--link-buff-sz-bits") {
            opts.link_buff_sz_bits = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--qkd-skr-bits-per-s") {
            opts.qkd_skr_bits_per_s = stod(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--latency-s") {
            opts.latency_s = stod(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--sim-duration-s") {
            opts.sim_duration_s = stod(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--relay-buffer-sz-chunks") {
            opts.relay_buffer_sz_chunks = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--print-arrival-times") {
            opts.print_arrival_times = true;
        } else {
            fail("Unknown argument: " + string(arg));
        }
    }

    if (opts.src_node.empty() || opts.tgt_node.empty()) fail("Source and target nodes are required");
    if (opts.chunk_size_bits <= 0) fail("--chunk-size-bits must be > 0");
    if (opts.link_buff_sz_bits <= 0) fail("--link-buff-sz-bits must be > 0");
    if (opts.qkd_skr_bits_per_s <= 0) fail("--qkd-skr-bits-per-s must be > 0");
    if (opts.latency_s < 0) fail("--latency-s must be >= 0");
    if (opts.sim_duration_s <= 0) fail("--sim-duration-s must be > 0");
    if (opts.relay_buffer_sz_chunks <= 0) fail("--relay-buffer-sz-chunks must be > 0");

    return opts;
}

unique_ptr<RwToken> make_token(const Options &opts, int src_idx, int tgt_idx, int seed) {
    if (opts.rw_variant == "R") return make_unique<RToken>(src_idx, tgt_idx, seed);
    if (opts.rw_variant == "NB") return make_unique<NbToken>(src_idx, tgt_idx, seed);
    if (opts.rw_variant == "LRV") return make_unique<LrvToken>(src_idx, tgt_idx, seed);
    if (opts.rw_variant == "HS") return make_unique<HsToken>(src_idx, tgt_idx, seed);
    if (opts.rw_variant == "HSB") return make_unique<HsbToken>(src_idx, tgt_idx, seed);
    if (opts.rw_variant == "BHS") return make_unique<BhsToken>(src_idx, tgt_idx, seed);
    return nullptr;
}

RunResult run_single_simulation(
    const vector<vector<int>> &adj,
    int src_idx,
    int tgt_idx,
    const Options &opts,
    int seed_offset
) {
    map<EdgeKey, LinkState> link;
    for (int u = 0; u < static_cast<int>(adj.size()); u++) {
        for (int v : adj[u]) {
            link.emplace(EdgeKey(u, v), LinkState{0.0, 0.0});
        }
    }

    auto link_state = [&](int a, int b) -> LinkState & {
        auto it = link.find(EdgeKey(a, b));
        if (it == link.end()) throw runtime_error("Missing edge in link state");
        return it->second;
    };

    RunResult result;
    priority_queue<Event, vector<Event>, EventGreater> pq;
    vector<int> relay_free(static_cast<int>(adj.size()), opts.relay_buffer_sz_chunks);
    vector<queue<Event>> slot_polling_events(static_cast<int>(adj.size()));
    vector<map<int, int>> sent_to_neighbor_count(static_cast<int>(adj.size()));
    const bool uses_send_state = (opts.rw_variant == "HSB" || opts.rw_variant == "BHS");

    auto schedule_first_hop = [&](double now, int source_node) -> void {
        if (adj[source_node].empty()) return;
        if (relay_free[source_node] <= 0) return;
        relay_free[source_node]--;
        auto pkt = make_shared<Packet>();
        pkt->source = source_node;
        pkt->target = tgt_idx;
        pkt->token = make_token(opts, src_idx, tgt_idx, seed_offset * 100000000 + result.emitted_chunks);
        if (!pkt->token) throw runtime_error("Unknown random walk variant: " + opts.rw_variant);
        RwToken::WalkNodeState node_state;
        node_state.node_idx = source_node;
        node_state.no_of_runs = max(1, result.emitted_chunks + 1);
        if (uses_send_state) {
            node_state.sent_to_neighbor_count = &sent_to_neighbor_count[source_node];
        }
        int next = pkt->token->choose_next_and_update(node_state, adj[source_node]);
        if (uses_send_state) {
            sent_to_neighbor_count[source_node][next]++;
        }
        double wait = link_state(source_node, next).reserve(
            now,
            opts.chunk_size_bits,
            opts.link_buff_sz_bits,
            opts.qkd_skr_bits_per_s
        );
        pq.push(Event{now + wait, EventType::OTP_AVAILABLE, source_node, source_node, next, pkt});
        result.emitted_chunks++;
    };

    for (int i = 0; i < opts.relay_buffer_sz_chunks; i++) {
        schedule_first_hop(0.0, src_idx);
    }

    auto try_admit = [&](double now, int node) -> void {
        if (!slot_polling_events[node].empty()) {
            if (relay_free[node] != 0) throw runtime_error("slot queue non-empty while relay_free != 0");
            Event og_ev = slot_polling_events[node].front();
            slot_polling_events[node].pop();
            pq.push(Event{now + opts.latency_s, EventType::SLOT_ACQUIRED, node, og_ev.from, -1, og_ev.pkt});
        } else {
            relay_free[node]++;
            if (relay_free[node] > opts.relay_buffer_sz_chunks) {
                throw runtime_error("relay buffer accounting overflow");
            }
        }
        if (node == src_idx) schedule_first_hop(now, node);
    };

    while (!pq.empty()) {
        Event ev = pq.top();
        pq.pop();
        if (ev.time > opts.sim_duration_s) break;

        if (ev.type == EventType::OTP_AVAILABLE) {
            pq.push(Event{ev.time + opts.latency_s, EventType::POLLED_BUFFER, ev.at, ev.next, -1, ev.pkt});
            continue;
        }

        if (ev.type == EventType::POLLED_BUFFER) {
            if (relay_free[ev.at] > 0) {
                relay_free[ev.at]--;
                pq.push(Event{ev.time + opts.latency_s, EventType::SLOT_ACQUIRED, ev.at, ev.from, -1, ev.pkt});
            } else {
                slot_polling_events[ev.at].push(ev);
            }
            continue;
        }

        if (ev.type == EventType::SLOT_ACQUIRED) {
            pq.push(Event{ev.time + opts.latency_s, EventType::KEY_ARRIVED, ev.at, ev.from, -1, ev.pkt});
            try_admit(ev.time, ev.at);
            continue;
        }

        if (ev.type == EventType::KEY_ARRIVED) {
            if (ev.at == ev.pkt->target) {
                result.arrived_chunks++;
                result.arrival_times.push_back(ev.time);
                try_admit(ev.time, ev.at);
                continue;
            }

            if (adj[ev.at].empty()) {
                try_admit(ev.time, ev.at);
                continue;
            }

            RwToken::WalkNodeState node_state;
            node_state.node_idx = ev.at;
            node_state.no_of_runs = max(1, result.emitted_chunks + 1);
            if (uses_send_state) {
                node_state.sent_to_neighbor_count = &sent_to_neighbor_count[ev.at];
            }
            int next = ev.pkt->token->choose_next_and_update(node_state, adj[ev.at]);
            if (uses_send_state) {
                sent_to_neighbor_count[ev.at][next]++;
            }
            double wait = link_state(ev.at, next).reserve(
                ev.time,
                opts.chunk_size_bits,
                opts.link_buff_sz_bits,
                opts.qkd_skr_bits_per_s
            );
            pq.push(Event{ev.time + wait, EventType::OTP_AVAILABLE, ev.at, ev.at, next, ev.pkt});
            continue;
        }
    }

    sort(result.arrival_times.begin(), result.arrival_times.end());
    return result;
}

TputStats compute_tput_stats(const RunResult &run, const Options &opts) {
    TputStats out;
    const double mean_tput_bits = static_cast<double>(run.arrived_chunks) *
                                  static_cast<double>(opts.chunk_size_bits) /
                                  opts.sim_duration_s;
    out.mean_tput_bits = static_cast<int>(llround(mean_tput_bits));
    out.emitted_chunks = run.emitted_chunks;
    out.arrival_times = run.arrival_times;
    return out;
}
