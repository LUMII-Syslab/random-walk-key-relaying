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
    POLLED_BUFFER = 1, // continuously polling for relay buffer space
    SLOT_ACQUIRED = 2, // acquired slot in relay buffer
    KEY_ARRIVED = 3, // key arrived at next (this) node
};

struct Event
{
    double time = 0.0;
    EventType type;
    int from = -1; // from which node the event is sent
    int at = -1; // at which node the event occurs
    int next = -1; // to which neighbor is OTP_AVAILABLE
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
        if(pkt->history.size()>=2) {
            const int prev = pkt->history[pkt->history.size() - 2];
            for (int n : nbrs)
                if (n != prev) choices.push_back(n);
        } else {
            choices = nbrs;
        }
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

    void reset_link_states()
    {
        for (auto &[key, state] : link)
            state.bit_balance = 0.0;
        for (auto &[key, state] : link)
            state.last_request = 0.0;
    }
};


Graph to_graph(const EdgesCsvGraph &g)
{
    map<EdgeKey, LinkState> link;
    for (size_t i = 0; i < g.adj.size(); i++)
        for (int v : g.adj[i])
            link.emplace(EdgeKey(i, v), LinkState{0.0, 0.0});
    return Graph{move(g.node_names), move(g.adj), move(link)};
}

static vector<pair<double, int>> run_simulation(Graph &g, int src, int tgt)
{
    const int N = static_cast<int>(g.adj.size());
    g.reset_link_states();

    vector<int> chunk_count(N, 0);
    vector<pair<double, int>> kept_events;
    kept_events.reserve(100000);

    priority_queue<Event, vector<Event>, EventGreater> pq;

    vector<int> relay_free(N, RELAY_BUFFER_CAPACITY);
    vector<queue<Event>> slot_polling_events(N);

    int next_packet_id = 0;

    auto schedule_first_hop = [&](double now, int source_node)
    {
        assert(relay_free[source_node] > 0);
        relay_free[source_node]--;
        if (g.adj[source_node].empty())
            return;
        auto pkt = make_shared<Packet>();
        pkt->id = next_packet_id++;
        pkt->source = source_node;
        pkt->target = tgt;
        pkt->history.clear();
        pkt->history.push_back(source_node);

        int next = choose_next_neighbor(g.adj[source_node], pkt);
        double wait = g.link_state(source_node, next).reserve(now, KEY_SIZE_BITS);
        pq.push(Event{now+wait, EventType::OTP_AVAILABLE, source_node, source_node, next, pkt});
    };

    for (int i = 0; i < RELAY_BUFFER_CAPACITY; i++)
        schedule_first_hop(0.0, src);

    // a free slot is available after sending the key or keeping a key
    auto try_admit = [&](double now, int node)
    {
        if(!slot_polling_events[node].empty())
        {
            assert(relay_free[node]==0);
            auto og_ev = slot_polling_events[node].front();
            slot_polling_events[node].pop();

            const double t = now + LATENCY_S;
            const EventType type = EventType::SLOT_ACQUIRED;
            const int from = node;
            const int to = og_ev.from;
            const shared_ptr<Packet> pkt = og_ev.pkt;
            pq.push(Event{t, type, from, to, -1, pkt});
        } else relay_free[node]++, assert(relay_free[node]<=RELAY_BUFFER_CAPACITY);

        if (node==src) schedule_first_hop(now, node);
    };

    while (!pq.empty())
    {
        Event ev = pq.top();
        pq.pop();
        if (ev.time > SIM_DURATION_S) break;

        if (ev.type == EventType::OTP_AVAILABLE)
        {
            // start polling neighbour to secure a slot in the relay buffer
            const double t = ev.time + LATENCY_S;
            const EventType type = EventType::POLLED_BUFFER;
            const int from = ev.at;
            const int to = ev.next;
            const shared_ptr<Packet> pkt = ev.pkt;
            pq.push(Event{t, type, from, to, -1, pkt});
        }

        if (ev.type == EventType::POLLED_BUFFER)
        {
            // relay_free keeps a counter of free slots in the buffer
            // if full, we keep a queue of nodes that are waiting for a slot
            // irl deployments, the source node would just keep polling
            // and the order would not be guaranteed
            if (relay_free[ev.at] > 0)
            {
                relay_free[ev.at]--;
                const double t = ev.time+LATENCY_S;
                const EventType type = EventType::SLOT_ACQUIRED;
                const int from = ev.at;
                const int to = ev.from;
                const shared_ptr<Packet> pkt = ev.pkt;
                pq.push(Event{t, type, from, to, -1, pkt});
            }
            else
            {
                slot_polling_events[ev.at].push(ev);
            }
        }

        if (ev.type == EventType::SLOT_ACQUIRED)
        {
            // we can now send the packet to the neighbor
            const double t = ev.time+LATENCY_S;
            const EventType type = EventType::KEY_ARRIVED;
            const int from = ev.at;
            const int to = ev.from;
            const shared_ptr<Packet> pkt = ev.pkt;
            pq.push(Event{t, type, from, to, -1, pkt});

            // since we have sent the key, a new spot is available in the buffer
            try_admit(ev.time, ev.at);
        }

        if (ev.type == EventType::KEY_ARRIVED)
        {
            ev.pkt->history.push_back(ev.at);

            bool keep = false;
            if (ev.pkt->target == -1) // proactive key relaying mode
            {
                const vector<int> &history = ev.pkt->history;
                const int hops_so_far = static_cast<int>(history.size()) - 1;
                double p_keep = keep_probability(chunk_count[ev.at], hops_so_far);
                uniform_real_distribution<double> uni01(0.0, 1.0);
                keep = (uni01(rng) < p_keep);
            }
            else keep = (ev.pkt->target == ev.at);

            if (keep) {
                chunk_count[ev.at]++;
                try_admit(ev.time, ev.at);
                kept_events.emplace_back(ev.time, ev.at);
                continue;
            } else {
                const int nxt = choose_next_neighbor(g.adj[ev.at], ev.pkt);
                const double wait = g.link_state(ev.at, nxt).reserve(ev.time, KEY_SIZE_BITS);
                const double t = ev.time + wait;
                const EventType type = EventType::OTP_AVAILABLE;
                const int from = ev.at;
                const int to = ev.at;
                const int next = nxt;
                const shared_ptr<Packet> pkt = ev.pkt;
                pq.push(Event{t, type, from, to, next, pkt});
            }
        }
    }

    return kept_events;
}

void write_kept_events(const vector<pair<double, int>> &kept_events, const string &out_path)
{
    fs::create_directories(fs::path(out_path).parent_path());
    ofstream out(out_path); assert(out);
    for (const auto &[t, idx] : kept_events) {
        out << fmt_2dp(t) << " " << idx << "\n";
    }
    cout<<"Wrote "<<out_path<<"\n";
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
        auto g = to_graph(load_edges_csv(edges_path));
        // int src = g.get_node_index(argv[2]);
        // int tgt = g.get_node_index(argv[3]);
        // auto kept_events = run_simulation(g, src, tgt);
        // sort(kept_events.begin(), kept_events.end(),
        //      [](const auto &a, const auto &b)
        //      { return a.first < b.first; });
            
        // write_kept_events(kept_events, "out2/rcv.txt");
        ofstream out("out2/throughput.csv"); assert(out);
        out<<"source,target,r_throughput,r_tput_rev\n";

        int total_pairs = g.adj.size()*(g.adj.size()-1)/2;
        int processed_pairs = 0;
        for(size_t src = 0; src < g.adj.size(); src++){
            for(size_t tgt = 0; tgt < g.adj.size(); tgt++){
                if(g.node_names[src] >= g.node_names[tgt]) continue;
                auto kept_events = run_simulation(g, src, tgt);
                sort(kept_events.begin(), kept_events.end(),
                     [](const auto &a, const auto &b)
                     { return a.first < b.first; });
                const double throughput = (kept_events.size()/SIM_DURATION_S)*(256.0/1000.0);
                auto kept_events_rev = run_simulation(g, tgt, src);
                sort(kept_events_rev.begin(), kept_events_rev.end(),
                     [](const auto &a, const auto &b)
                     { return a.first < b.first; });
                const double throughput_rev = (kept_events_rev.size()/SIM_DURATION_S)*(256.0/1000.0);
                out<<g.node_names[src]<<","<<g.node_names[tgt]<<","<<fmt_3dp(throughput)<<","<<fmt_3dp(throughput_rev)<<"\n";

                processed_pairs++;
                cout<<"Processed "<<processed_pairs<<"/"<<total_pairs<<" pairs\r";
                cout.flush();
            }
        }
        return 0;
    }
    catch (const exception &e)
    {
        cerr << "Fatal error: " << e.what() << "\n";
        return 1;
    }
}
