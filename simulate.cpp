/*
Proactive random-walk key relaying simulation (C++).

Twist vs simulate.py:
- There is NO destination node.
- Each packet ("chunk") performs a random walk on an undirected graph.
- When a packet arrives at a node, the node may "keep" the chunk in its key buffer
  (i.e., store it locally), terminating the walk.
- Each node maintains:
    (1) a relay "source slot" (we keep exactly one active chunk per node source)
    (2) a key buffer fill counter (simple integer counter; capacity is configurable)

Keep probability:
  p_keep = clamp(1 - b / h, 0, 1)
where:
  b in [0,1] is the key-buffer fill level (keys_stored / key_capacity),
  h is the packet history length in hops (>=1 on first arrival).

Events are scheduled in a min-heap priority queue.

Input:
  ./simulate <edge_list.csv>
Expected CSV header contains at least: Source,Target

Output:
  out2/kept_chunks.txt with lines:
    <time_offset_seconds> <NODE>

Simulation duration is fixed to 1000s.
*/

#include <algorithm>
#include <cassert>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <memory>
#include <queue>
#include <random>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>
#include <iomanip>

#include "sim_helpers.hpp"

using namespace std;
namespace fs = std::filesystem;

static constexpr int KEY_SIZE_BITS = 256;
static constexpr int LINK_BUFF_BITS = 100000;
static constexpr double QKD_SKR_BITS_PER_S = 1000.0;
static constexpr double LATENCY_S = 0.05;
static constexpr double SIM_DURATION_S = 1000.0;

// Proactive-specific knobs
static constexpr int KEY_BUFFER_CAPACITY = 1000;   // per node, in chunks
static constexpr int RELAY_BUFFER_CAPACITY = 100000; // per node, in chunks (like simulate.py)
static constexpr uint32_t RNG_SEED = 2026;

struct Packet {
    int id = -1;
    int source = -1;             // origin node index
    vector<int> history;    // node indices visited (includes source, current)
};

struct LinkState {
    double bit_balance = 0.0;
    double last_request = 0.0;

    double reserve(double current_time, int necessary_bits) {
        if (necessary_bits > LINK_BUFF_BITS) {
            throw runtime_error("necessary_bits > LINK_BUFF_BITS");
        }
        if (current_time < last_request) {
            throw runtime_error("current_time < last_request");
        }

        // accumulate newly generated bits since last reservation request
        const double dt = current_time - last_request;
        bit_balance += dt * QKD_SKR_BITS_PER_S;

        // waiting until enough balance
        const double waiting = max(0.0, (necessary_bits - bit_balance) / QKD_SKR_BITS_PER_S);

        // IMPORTANT: last_request is the time we *issued* the reservation, not when it is fulfilled.
        last_request = current_time;
        bit_balance -= necessary_bits;
        return waiting;
    }
};

enum class EventType : uint8_t {
    ARRIVE = 1,   // packet arrives at node "to"
    PROCESS = 2,  // admitted into relay buffer, decide keep/forward
    DISPATCH = 3, // release relay slot and either keep or forward
};

struct Event {
    double time = 0.0;
    EventType type = EventType::ARRIVE;
    int to = -1;
    int next = -1;     // used when forwarding
    bool keep = false; // used in DISPATCH
    shared_ptr<Packet> pkt;
};

struct EventGreater {
    bool operator()(const Event& a, const Event& b) const {
        // min-heap by time
        return a.time > b.time;
    }
};

static uint64_t edge_key(int a, int b) {
    if (a > b) swap(a, b);
    return (static_cast<uint64_t>(static_cast<uint32_t>(a)) << 32) |
           static_cast<uint32_t>(b);
}

static double clamp01(double x) {
    if (x < 0.0) return 0.0;
    if (x > 1.0) return 1.0;
    return x;
}

static int choose_next_neighbor(
    int current,
    int prev,
    const vector<vector<int>>& adj,
    mt19937& rng
) {
    const auto& nbrs = adj[current];
    if (nbrs.empty()) return -1;
    if (nbrs.size() == 1) return nbrs[0];
    // Random choice; allow backtracking (proactive basic RW).
    uniform_int_distribution<int> dist(0, static_cast<int>(nbrs.size()) - 1);
    (void)prev;
    return nbrs[dist(rng)];
}

static double keep_probability(
    int node_key_count,
    int history_hops
) {
    const double b = (KEY_BUFFER_CAPACITY > 0)
        ? (static_cast<double>(node_key_count) / static_cast<double>(KEY_BUFFER_CAPACITY))
        : 0.0;
    const double h = max(1, history_hops); // in hops
    return clamp01(1.0 - b / h);
}

struct GraphData {
    vector<string> node_names;
    vector<vector<int>> adj;
    unordered_map<uint64_t, LinkState> link;
};

static GraphData load_graph_from_edges_csv(const string& edges_path) {
    ifstream in(edges_path);
    if (!in) throw runtime_error("Failed to open edges file: " + edges_path);

    unordered_map<string, int> node_idx;
    vector<string> node_names;
    vector<pair<int, int>> edges;

    string header_line;
    if (!getline(in, header_line)) throw runtime_error("Empty edges file");

    auto header = split_csv_line(header_line);
    int col_source = -1, col_target = -1;
    for (int i = 0; i < static_cast<int>(header.size()); i++) {
        string h = header[i];
        for (auto& ch : h) ch = static_cast<char>(tolower(static_cast<unsigned char>(ch)));
        if (h == "source") col_source = i;
        if (h == "target") col_target = i;
    }
    if (col_source < 0 || col_target < 0) {
        throw runtime_error("CSV header must contain Source,Target columns");
    }

    string line;
    while (getline(in, line)) {
        if (trim(line).empty()) continue;
        auto cols = split_csv_line(line);
        if (col_source >= static_cast<int>(cols.size()) || col_target >= static_cast<int>(cols.size())) continue;
        const string s = cols[col_source];
        const string t = cols[col_target];
        if (s.empty() || t.empty()) continue;
        int u = get_or_add_node(s, node_idx, node_names);
        int v = get_or_add_node(t, node_idx, node_names);
        if (u == v) continue;
        edges.emplace_back(u, v);
    }

    const int N = static_cast<int>(node_names.size());
    if (N == 0) throw runtime_error("No nodes found in edge list");

    vector<vector<int>> adj(N);
    for (auto [u, v] : edges) {
        adj[u].push_back(v);
        adj[v].push_back(u);
    }

    unordered_map<uint64_t, LinkState> link;
    link.reserve(edges.size() * 2 + 1);
    for (auto [u, v] : edges) {
        const uint64_t k = edge_key(u, v);
        (void)link.emplace(k, LinkState{0.0, 0.0});
    }

    return GraphData{move(node_names), move(adj), move(link)};
}

static vector<pair<double, int>> run_simulation(
    const vector<vector<int>>& adj,
    unordered_map<uint64_t, LinkState>& link
) {
    const int N = static_cast<int>(adj.size());

    vector<int> key_count(N, 0);
    vector<pair<double, int>> kept_events;
    kept_events.reserve(100000);

    mt19937 rng(RNG_SEED);
    priority_queue<Event, vector<Event>, EventGreater> pq;

    vector<int> relay_free(N, RELAY_BUFFER_CAPACITY);
    vector<deque<shared_ptr<Packet>>> relay_wait(N);

    int next_packet_id = 0;

    auto schedule_first_hop = [&](double now, int source_node) {
        if (adj[source_node].empty()) return;
        auto pkt = make_shared<Packet>();
        pkt->id = next_packet_id++;
        pkt->source = source_node;
        pkt->history.clear();
        pkt->history.push_back(source_node);

        int next = choose_next_neighbor(source_node, -1, adj, rng);
        if (next < 0) return;

        const uint64_t k = edge_key(source_node, next);
        double wait = link.at(k).reserve(now, KEY_SIZE_BITS);
        double arrive_t = now + wait + LATENCY_S;
        pq.push(Event{arrive_t, EventType::ARRIVE, next, -1, false, pkt});
    };

    for (int s = 0; s < N; s++) schedule_first_hop(0.0, s);

    auto try_admit = [&](double now, int node) {
        if (relay_free[node] <= 0) return;
        if (relay_wait[node].empty()) return;
        auto pkt = relay_wait[node].front();
        relay_wait[node].pop_front();
        relay_free[node]--;
        pq.push(Event{now + LATENCY_S, EventType::PROCESS, node, -1, false, pkt});
    };

    while (!pq.empty()) {
        Event ev = pq.top();
        pq.pop();
        if (ev.time > SIM_DURATION_S) break;
        if (!ev.pkt) continue;
        const int node = ev.to;
        auto& pkt = *ev.pkt;

        if (ev.type == EventType::ARRIVE) {
            pkt.history.push_back(node);
            if (relay_free[node] > 0) {
                relay_free[node]--;
                pq.push(Event{ev.time + LATENCY_S, EventType::PROCESS, node, -1, false, ev.pkt});
            } else {
                relay_wait[node].push_back(ev.pkt);
            }
            continue;
        }

        if (ev.type == EventType::PROCESS) {
            const int hops_so_far = static_cast<int>(pkt.history.size()) - 1;
            double p_keep = keep_probability(key_count[node], hops_so_far);
            uniform_real_distribution<double> uni01(0.0, 1.0);
            bool keep = (uni01(rng) < p_keep);

            if (keep) {
                pq.push(Event{ev.time + LATENCY_S, EventType::DISPATCH, node, -1, true, ev.pkt});
                continue;
            }

            int prev = (pkt.history.size() >= 2) ? pkt.history[pkt.history.size() - 2] : -1;
            int nxt = choose_next_neighbor(node, prev, adj, rng);
            if (nxt < 0) {
                pq.push(Event{ev.time + LATENCY_S, EventType::DISPATCH, node, -1, true, ev.pkt});
                continue;
            }
            pq.push(Event{ev.time + LATENCY_S, EventType::DISPATCH, node, nxt, false, ev.pkt});
            continue;
        }

        if (ev.type == EventType::DISPATCH) {
            relay_free[node]++;
            if (relay_free[node] > RELAY_BUFFER_CAPACITY) relay_free[node] = RELAY_BUFFER_CAPACITY;
            try_admit(ev.time, node);

            if (ev.keep) {
                if (key_count[node] < KEY_BUFFER_CAPACITY) key_count[node] += 1;
                kept_events.push_back({ev.time, node});
                schedule_first_hop(ev.time, pkt.source);
                continue;
            }

            const int nxt = ev.next;
            const uint64_t k = edge_key(node, nxt);
            auto it = link.find(k);
            if (it == link.end()) {
                schedule_first_hop(ev.time, pkt.source);
                continue;
            }
            double wait = it->second.reserve(ev.time, KEY_SIZE_BITS);
            double arrive_t = ev.time + wait + LATENCY_S;
            pq.push(Event{arrive_t, EventType::ARRIVE, nxt, -1, false, ev.pkt});
            continue;
        }
    }

    return kept_events;
}

int main(int argc, char** argv) {
    try {
        if (argc < 2) {
            cerr << "Usage: " << argv[0] << " <edge_list.csv>\n";
            return 2;
        }

        const string edges_path = argv[1];
        auto g = load_graph_from_edges_csv(edges_path);
        auto kept_events = run_simulation(g.adj, g.link);

        fs::path out_dir = fs::path("out2");
        fs::create_directories(out_dir);
        fs::path out_path = out_dir / "kept_chunks.txt";
        ofstream out(out_path);
        if (!out) {
            cerr << "Failed to open output: " << out_path << "\n";
            return 2;
        }

        auto fmt_time = [](double t) -> string {
            // "at most two digits after decimal": print 2dp then trim trailing zeros/dot.
            ostringstream oss;
            oss.setf(ios::fixed);
            oss << setprecision(2) << t;
            string s = oss.str();
            // trim trailing zeros
            while (!s.empty() && s.back() == '0') s.pop_back();
            if (!s.empty() && s.back() == '.') s.pop_back();
            return s;
        };

        sort(kept_events.begin(), kept_events.end(),
             [](const auto& a, const auto& b) { return a.first < b.first; });

        // One line per keep event: "<time> <NODE>"
        for (const auto& [t, idx] : kept_events) {
            out << fmt_time(t) << " " << g.node_names[idx] << "\n";
        }

        cout << "Done. Wrote " << out_path.string() << "\n";
        return 0;
    } catch (const exception& e) {
        cerr << "Fatal error: " << e.what() << "\n";
        return 1;
    }
}
