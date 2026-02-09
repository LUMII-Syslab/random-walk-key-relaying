#include <algorithm>
#include <cassert>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <queue>
#include <random>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

#include "helpers.hpp"

using namespace std;
namespace fs = std::filesystem;
static constexpr uint32_t RNG_SEED = 2026;
static mt19937 rng(RNG_SEED);

enum RandomWalkVariant
{
    R,
    NB,
    LRV
};

static constexpr int KEY_SIZE_BITS = 256;
static constexpr int LINK_BUFF_BITS = 100000;
static constexpr double QKD_SKR_BITS_PER_S = 1000.0;
static constexpr double LATENCY_S = 0.05;
static constexpr double SIM_DURATION_S = 1000.0;
static constexpr int RELAY_BUFFER_CAPACITY = 100000; // per node, in chunks

static constexpr RandomWalkVariant RANDOM_WALK_VARIANT = R;

// proactive-specific knobs
static constexpr int KEY_BUFFER_CAPACITY = 1000; // per node, in chunks

struct Packet
{
    int id = -1;
    int source = -1;     // origin node index
    int target = -1;     // destination node index (can be -1 for proactive)
    vector<int> history; // node indices visited (includes source, current)
};

struct LinkState
{
    double bit_balance = 0.0;
    double last_request = 0.0;

    double reserve(double current_time, int necessary_bits)
    {
        if (necessary_bits > LINK_BUFF_BITS)
            throw runtime_error("necessary_bits > LINK_BUFF_BITS");
        if (current_time < last_request)
            throw runtime_error("current_time < last_request");

        // accumulate newly generated bits since last reservation request
        const double dt = current_time - last_request;
        bit_balance += dt * QKD_SKR_BITS_PER_S;

        // waiting until enough balance
        const double waiting =
            max(0.0, (necessary_bits - bit_balance) / QKD_SKR_BITS_PER_S);

        // IMPORTANT: last_request is the time we *issued* the reservation
        last_request = current_time;
        bit_balance -= necessary_bits;
        return waiting;
    }
};

enum class EventType : uint8_t
{
    OTP_AVAILABLE = 0, // OTP is available for encryption
    POLL_BUFFER = 1, // continuously polling for relay buffer space
    SLOT_ACQUIRED = 2, // acquired slot in relay buffer
    KEY_ARRIVED = 3, // key arrived at next (this) node
};

struct Event
{
    double time = 0.0;
    EventType type;
    shared_ptr<Packet> pkt;
};

struct EventGreater
{
    bool operator()(const Event &a, const Event &b) const
    {
        // min-heap by time
        return a.time > b.time;
    }
};

struct EdgeKey
{
    int u = -1;
    int v = -1;

    EdgeKey() = default;
    EdgeKey(int a, int b)
    {
        u = min(a, b);
        v = max(a, b);
    }

    friend bool operator==(const EdgeKey &a, const EdgeKey &b)
    {
        return a.u == b.u && a.v == b.v;
    }

    friend bool operator<(const EdgeKey &a, const EdgeKey &b)
    {
        if (a.u != b.u)
            return a.u < b.u;
        return a.v < b.v;
    }
};

static int choose_next_neighbor(const vector<int> &nbrs, const shared_ptr<Packet> &pkt)
{
    assert(!nbrs.empty());
    if (nbrs.size() == 1)
        return nbrs[0];

    vector<int> choices;

    switch (RANDOM_WALK_VARIANT)
    {
    case RandomWalkVariant::R:
        choices = nbrs;
        break;
    case RandomWalkVariant::NB:
    {
        assert(pkt->history.size() >= 2);
        const int prev = pkt->history.back();
        for (int n : nbrs)
            if (n != prev)
                choices.push_back(n);
        break;
    }
    case RandomWalkVariant::LRV:
    {
        // Least-recently-visited (LRV) over the packet's own history:
        // pick neighbor with minimal "last seen index"; never-seen wins.
        map<int, int> last_idx;
        for (size_t i = 0; i < pkt->history.size(); i++)
            last_idx[pkt->history[i]] = static_cast<int>(i);

        int best_last = numeric_limits<int>::max();
        for (int n : nbrs)
        {
            const auto it = last_idx.find(n);
            const int last = (it == last_idx.end()) ? -1 : it->second;
            if (last < best_last)
            {
                best_last = last;
                choices.clear();
            }
            if (last == best_last)
                choices.push_back(n);
        }
        break;
    }
    default:
        throw runtime_error("Invalid random walk variant");
    }

    assert(!choices.empty());
    uniform_int_distribution<int> dist(0, static_cast<int>(choices.size()) - 1);
    return choices[dist(rng)];
}

static double keep_probability(int node_key_count, int history_hops)
{
    const double b = (KEY_BUFFER_CAPACITY > 0)
                         ? (static_cast<double>(node_key_count) /
                            static_cast<double>(KEY_BUFFER_CAPACITY))
                         : 0.0;
    const double h = max(1, history_hops); // in hops
    return clamp01(1.0 - b / h);
}

struct Graph
{
    vector<string> node_names;
    vector<vector<int>> adj;
    map<EdgeKey, LinkState> link;

    LinkState &link_state(int a, int b)
    {
        auto it = link.find(EdgeKey(a, b));
        if (it == link.end())
            throw runtime_error("Missing edge in graph link state");
        return it->second;
    }

    LinkState *link_state_ptr(int a, int b)
    {
        auto it = link.find(EdgeKey(a, b));
        if (it == link.end())
            return nullptr;
        return &it->second;
    }

    int get_node_index(const string &name) const
    {
        for (size_t i = 0; i < node_names.size(); i++)
            if (node_names[i] == name)
                return i;
        throw runtime_error("Node not found in graph: " + name);
    }
};

static Graph load_graph_from_edges_csv(const string &edges_path)
{
    ifstream in(edges_path);
    if (!in)
        throw runtime_error("Failed to open edges file: " + edges_path);

    unordered_map<string, int> node_idx;
    vector<string> node_names;
    vector<pair<int, int>> edges;

    string header_line;
    if (!getline(in, header_line))
        throw runtime_error("Empty edges file");

    auto header = split_csv_line(header_line);
    int col_source = -1, col_target = -1;
    for (int i = 0; i < static_cast<int>(header.size()); i++)
    {
        string h = header[i];
        for (auto &ch : h)
            ch = static_cast<char>(tolower(static_cast<unsigned char>(ch)));
        if (h == "source")
            col_source = i;
        if (h == "target")
            col_target = i;
    }
    if (col_source < 0 || col_target < 0)
    {
        throw runtime_error("CSV header must contain Source,Target columns");
    }

    string line;
    while (getline(in, line))
    {
        if (trim(line).empty())
            continue;
        auto cols = split_csv_line(line);
        if (col_source >= static_cast<int>(cols.size()) ||
            col_target >= static_cast<int>(cols.size()))
            continue;
        const string s = cols[col_source];
        const string t = cols[col_target];
        if (s.empty() || t.empty())
            continue;
        int u = get_or_add_node(s, node_idx, node_names);
        int v = get_or_add_node(t, node_idx, node_names);
        if (u == v)
            continue;
        edges.emplace_back(u, v);
    }

    const int N = static_cast<int>(node_names.size());
    if (N == 0)
        throw runtime_error("No nodes found in edge list");

    vector<vector<int>> adj(N);
    for (auto [u, v] : edges)
    {
        adj[u].push_back(v);
        adj[v].push_back(u);
    }

    map<EdgeKey, LinkState> link;
    for (auto [u, v] : edges)
    {
        (void)link.emplace(EdgeKey(u, v), LinkState{0.0, 0.0});
    }

    return Graph{move(node_names), move(adj), move(link)};
}

static vector<pair<double, int>> run_simulation(Graph &g, int src, int tgt)
{
    const int N = static_cast<int>(g.adj.size());

    vector<int> key_count(N, 0);
    vector<pair<double, int>> kept_events;
    kept_events.reserve(100000);

    priority_queue<Event, vector<Event>, EventGreater> pq;

    vector<int> relay_free(N, RELAY_BUFFER_CAPACITY);
    vector<deque<shared_ptr<Packet>>> relay_wait(N);

    int next_packet_id = 0;

    auto schedule_first_hop = [&](double now, int source_node)
    {
        if (g.adj[source_node].empty())
            return;
        auto pkt = make_shared<Packet>();
        pkt->id = next_packet_id++;
        pkt->source = source_node;
        pkt->target = tgt;
        pkt->history.clear();
        pkt->history.push_back(source_node);

        int next = choose_next_neighbor(g.adj[source_node], pkt);
        if (next < 0)
            return;

        double wait = g.link_state(source_node, next).reserve(now, KEY_SIZE_BITS);
        double arrive_t = now + wait + LATENCY_S;
        pq.push(Event{arrive_t, EventType::ARRIVE, next, -1, false, pkt});
    };

    for (int i = 0; i < RELAY_BUFFER_CAPACITY; i++)
        schedule_first_hop(0.0, src);

    auto try_admit = [&](double now, int node)
    {
        if (relay_free[node] <= 0)
            return;
        if (relay_wait[node].empty())
            return;
        auto pkt = relay_wait[node].front();
        relay_wait[node].pop_front();
        relay_free[node]--;
        pq.push(Event{now + LATENCY_S, EventType::PROCESS, node, -1, false, pkt});
    };

    while (!pq.empty())
    {
        Event ev = pq.top();
        pq.pop();
        if (ev.time > SIM_DURATION_S)
            break;
        if (!ev.pkt)
            continue;
        const int node = ev.to;
        auto &pkt = *ev.pkt;

        if (ev.type == EventType::ARRIVE)
        {
            pkt.history.push_back(node);
            if (relay_free[node] > 0)
            {
                relay_free[node]--;
                pq.push(Event{ev.time, EventType::PROCESS, node, -1, false, ev.pkt});
            }
            else
            {
                relay_wait[node].push_back(ev.pkt);
            }
            continue;
        }

        if (ev.type == EventType::PROCESS)
        {
            bool keep = false;
            if (pkt.target == -1)
            {
                const int hops_so_far = static_cast<int>(pkt.history.size()) - 1;
                double p_keep = keep_probability(key_count[node], hops_so_far);
                uniform_real_distribution<double> uni01(0.0, 1.0);
                keep = (uni01(rng) < p_keep);
            }
            else keep = (pkt.target == node);

            if (keep) {
                pq.push(Event{ev.time, EventType::DISPATCH, node, -1, true, ev.pkt});
                continue;
            }

            int nxt = choose_next_neighbor(g.adj[node], ev.pkt);
            pq.push(Event{ev.time, EventType::DISPATCH, node, nxt, false, ev.pkt});
            continue;
        }

        if (ev.type == EventType::DISPATCH)
        {
            relay_free[node]++;
            if (relay_free[node] > RELAY_BUFFER_CAPACITY)
                relay_free[node] = RELAY_BUFFER_CAPACITY;
            try_admit(ev.time, node);

            if (ev.keep)
            {
                if (key_count[node] < KEY_BUFFER_CAPACITY)
                    key_count[node] += 1;
                kept_events.push_back({ev.time, node});
                schedule_first_hop(ev.time, pkt.source);
                continue;
            }

            const int nxt = ev.next;
            LinkState *ls = g.link_state_ptr(node, nxt);
            if (!ls)
            {
                schedule_first_hop(ev.time, pkt.source);
                continue;
            }
            double wait = ls->reserve(ev.time, KEY_SIZE_BITS);
            double arrive_t = ev.time + wait + LATENCY_S;
            pq.push(Event{arrive_t, EventType::ARRIVE, nxt, -1, false, ev.pkt});
            continue;
        }
    }

    return kept_events;
}

int main(int argc, char **argv)
{
    try
    {
        if (argc < 2)
        {
            cerr << "Usage: " << argv[0] << " <edge_list.csv>\n";
            return 2;
        }

        const string edges_path = argv[1];
        auto g = load_graph_from_edges_csv(edges_path);
        int src = g.get_node_index(argv[2]);
        int tgt = g.get_node_index(argv[3]);
        auto kept_events = run_simulation(g, src, tgt);

        fs::path out_dir = fs::path("out2");
        fs::create_directories(out_dir);
        fs::path out_path = out_dir / "rcv.txt";
        ofstream out(out_path);
        if (!out)
        {
            cerr << "Failed to open output: " << out_path << "\n";
            return 2;
        }

        sort(kept_events.begin(), kept_events.end(),
             [](const auto &a, const auto &b)
             { return a.first < b.first; });

        // One line per keep event: "<time> <NODE>"
        for (const auto &[t, idx] : kept_events)
            out << fmt_2dp(t) << " " << g.node_names[idx] << "\n";

        cout << "Done. Wrote " << out_path.string() << "\n";
        return 0;
    }
    catch (const exception &e)
    {
        cerr << "Fatal error: " << e.what() << "\n";
        return 1;
    }
}
