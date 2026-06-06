#include <algorithm>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <map>
#include <memory>
#include <queue>
#include <string_view>
#include <vector>
#include "cli.hpp"
#include "graph.hpp"
#include "lerw.hpp"
#include "walk.hpp"

using namespace std;

struct Options {
    WalkCliOpts walk;
    bool erase_loops = false;
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

enum class EventType : uint8_t {
    OTP_AVAILABLE = 0,
    POLLED_BUFFER = 1,
    SLOT_ACQUIRED = 2,
    KEY_ARRIVED = 3,
};

struct Packet {
    int source = -1;
    int target = -1;
    int hops = 0;
    int creation_seq = -1;
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

struct WaitingEventGreater {
    bool operator()(const Event &a, const Event &b) const {
        if (a.pkt->creation_seq != b.pkt->creation_seq) {
            return a.pkt->creation_seq > b.pkt->creation_seq;
        }
        if (a.time != b.time) {
            return a.time > b.time;
        }
        if (a.from != b.from) {
            return a.from > b.from;
        }
        return a.at > b.at;
    }
};

struct RunResult {
    int arrived_chunks = 0;
    int emitted_chunks = 0;
    vector<double> arrival_times;
};

Options parse_args(int argc, char **argv);
RunResult run_single_simulation(QkdNetwork &net, int src_idx, int tgt_idx, const Options &opts, int seed_offset);
TputStats compute_tput_stats(const RunResult &run, const Options &opts);

int main(int argc, char **argv) {
    Options opts = parse_args(argc, argv);
    QkdNetwork net = opts.walk.edges_csv.empty() ? QkdNetwork(cin) : QkdNetwork(opts.walk.edges_csv);

    int src_idx = net.node_index(opts.walk.src_node);
    int tgt_idx = net.node_index(opts.walk.tgt_node);

    RunResult run = run_single_simulation(net, src_idx, tgt_idx, opts, 0);
    TputStats stats = compute_tput_stats(run, opts);
    stats.print(cout, opts.print_arrival_times);
    return 0;
}

Options parse_args(int argc, char **argv) {
    Options opts;
    opts.walk.rw_variant = "LRV";
    CliParser cli(argc, argv);
    WalkFlagOpts walk_flags;
    walk_flags.include_runs = false;
    cli.reg_walk_flags(opts.walk, walk_flags);
    cli.reg_int("--chunk-size-bits", {}, opts.chunk_size_bits);
    cli.reg_int("--link-buff-sz-bits", {}, opts.link_buff_sz_bits);
    cli.reg_double("--qkd-skr-bits-per-s", {}, opts.qkd_skr_bits_per_s);
    cli.reg_double("--latency-s", {}, opts.latency_s);
    cli.reg_double("--sim-duration-s", {}, opts.sim_duration_s);
    cli.reg_int("--relay-buffer-sz-chunks", {}, opts.relay_buffer_sz_chunks);
    cli.reg_bool("--erase-loops", {}, opts.erase_loops);
    cli.reg_bool("--print-arrival-times", {}, opts.print_arrival_times);
    cli.parse();

    validate_walk_endpoints(cli, opts.walk);
    if (opts.chunk_size_bits <= 0) cli.fail("--chunk-size-bits must be > 0");
    if (opts.link_buff_sz_bits <= 0) cli.fail("--link-buff-sz-bits must be > 0");
    if (opts.qkd_skr_bits_per_s <= 0) cli.fail("--qkd-skr-bits-per-s must be > 0");
    if (opts.latency_s < 0) cli.fail("--latency-s must be >= 0");
    if (opts.sim_duration_s <= 0) cli.fail("--sim-duration-s must be > 0");
    if (opts.relay_buffer_sz_chunks <= 0) cli.fail("--relay-buffer-sz-chunks must be > 0");

    return opts;
}

RunResult run_single_simulation(
    QkdNetwork &net,
    int src_idx,
    int tgt_idx,
    const Options &opts,
    int seed_offset
) {
    const auto &adj = net.adj_list();

    RunResult result;
    priority_queue<Event, vector<Event>, EventGreater> pq;
    vector<int> relay_free(static_cast<int>(adj.size()), opts.relay_buffer_sz_chunks);
    vector<priority_queue<Event, vector<Event>, WaitingEventGreater>> slot_polling_events(static_cast<int>(adj.size()));
    const int node_count = static_cast<int>(adj.size());

    auto schedule_first_hop = [&](double now, int source_node) -> void {
        if (adj[source_node].empty()) return;
        if (relay_free[source_node] <= 0) return;
        relay_free[source_node]--;
        auto pkt = make_shared<Packet>();
        pkt->source = source_node;
        pkt->target = tgt_idx;
        pkt->creation_seq = result.emitted_chunks;
        const int seed = seed_offset * 100000000 + result.emitted_chunks;
        if (opts.erase_loops) {
            vector<int> loop_erased_path = sample_loop_erased_path(
                adj,
                opts.walk.rw_variant,
                source_node,
                tgt_idx,
                seed,
                node_count
            );
            pkt->token = make_unique<FixedPathToken>(std::move(loop_erased_path));
        } else {
            pkt->token = make_rw_token(opts.walk.rw_variant, src_idx, tgt_idx, seed, node_count);
        }
        if (!pkt->token) throw runtime_error("Unknown random walk variant: " + opts.walk.rw_variant);
        int next = pkt->token->choose_next_and_update(source_node, adj[source_node]);
        pkt->hops = 1;
        if (pkt->hops > 1000) throw runtime_error("Random walk exceeded 1000 steps");
        double wait = net.link_state(source_node, next).reserve(
            now,
            opts.chunk_size_bits,
            opts.link_buff_sz_bits,
            opts.qkd_skr_bits_per_s
        );
        pq.push(Event{now + wait, EventType::OTP_AVAILABLE, source_node, source_node, next, pkt});
        result.emitted_chunks++;
    };

    for (int i = 0; i < opts.relay_buffer_sz_chunks && i < opts.sim_duration_s*adj[src_idx].size(); i++) {
        schedule_first_hop(0.0, src_idx);
    }

    auto release_slot = [&](double now, int node) -> void {
        relay_free[node]++;
        if (!slot_polling_events[node].empty()) {
            relay_free[node]--;
            if (relay_free[node] != 0) throw runtime_error("slot queue non-empty while relay_free != 0");
            Event og_ev = slot_polling_events[node].top();
            slot_polling_events[node].pop();
            pq.push(Event{now + opts.latency_s, EventType::SLOT_ACQUIRED, node, og_ev.from, -1, og_ev.pkt});
        } else {
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
            continue;
        }

        if (ev.type == EventType::KEY_ARRIVED) {
            release_slot(ev.time, ev.from);

            if (ev.at == ev.pkt->target) {
                result.arrived_chunks++;
                result.arrival_times.push_back(ev.time);
                release_slot(ev.time, ev.at);
                continue;
            }

            if (adj[ev.at].empty()) {
                release_slot(ev.time, ev.at);
                continue;
            }

            int next = ev.pkt->token->choose_next_and_update(ev.at, adj[ev.at]);
            ev.pkt->hops++;
            if (ev.pkt->hops > 1000) throw runtime_error("Random walk exceeded 1000 steps");
            double wait = net.link_state(ev.at, next).reserve(
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
