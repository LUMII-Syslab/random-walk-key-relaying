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
#include <numeric>
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

// Selected at runtime from argv in main(). No default allowed.
static RandomWalkVariant RANDOM_WALK_VARIANT;


static RandomWalkVariant parse_walk_variant(const string &s_raw)
{
    const string s = to_upper_ascii(s_raw);
    if (s == "R")
        return RandomWalkVariant::R;
    if (s == "NB")
        return RandomWalkVariant::NB;
    if (s == "LRV")
        return RandomWalkVariant::LRV;
    throw runtime_error("Invalid walk variant: '" + s_raw + "' (expected R, NB, or LRV)");
}

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

struct ArrivedPacket{
    double time;
    vector<int> history;
    int source_node() const { return history[0]; }
    int finished_at() const { return history.back(); }
};

static vector<ArrivedPacket> run_simulation(Graph &g, int src, int tgt)
{
    const int N = static_cast<int>(g.adj.size());
    g.reset_link_states();

    vector<int> chunk_count(N, 0);
    vector<ArrivedPacket> arrived_packets;

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
                arrived_packets.emplace_back(ev.time, ev.pkt->history);
                assert(arrived_packets.back().source_node() == src);
                assert(arrived_packets.back().finished_at() == ev.at);
                if(tgt != -1) assert(ev.at == tgt);
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

    sort(arrived_packets.begin(), arrived_packets.end(),
         [](const auto &a, const auto &b)
         { return make_tuple(a.time,a.source_node(),a.finished_at()) < make_tuple(b.time,b.source_node(),b.finished_at()); });

    return arrived_packets;
}

struct HopStats{
    int min_hops = numeric_limits<int>::max();
    int max_hops = numeric_limits<int>::min();
    double mean_hops = 0.0;
    int q1_hops = 0;
    int q2_hops = 0;
    int q3_hops = 0;
};

HopStats compute_hop_stats(const vector<ArrivedPacket> &arrived_packets)
{
    assert(arrived_packets.size()>0);
    HopStats stats;

    vector<int> hops;

    // first pass: compute min, max, mean
    for(const auto &pkt : arrived_packets)
        hops.push_back(static_cast<int>(pkt.history.size()) - 1);
    stats.min_hops = *min_element(hops.begin(), hops.end());
    stats.max_hops = *max_element(hops.begin(), hops.end());
    double sum_hops = accumulate(hops.begin(), hops.end(), 0);
    stats.mean_hops = sum_hops / arrived_packets.size();

    // second pass: compute q1, q2, q3
    sort(hops.begin(), hops.end());
    stats.q1_hops = hops[static_cast<size_t>(0.25 * hops.size())];
    stats.q2_hops = hops[static_cast<size_t>(0.50 * hops.size())];
    stats.q3_hops = hops[static_cast<size_t>(0.75 * hops.size())];
    return stats;
}

double compute_throughput(const vector<ArrivedPacket> &arrived_packets)
{
    return static_cast<double>(arrived_packets.size())/SIM_DURATION_S*(256.0/1000.0);
}

struct ExposureStats{
    double max_vis_prob = 0.0; // that is not source or target
    int max_vis_node = -1;

    double max_vis_prob_2 = 0.0; // second most visited node. that is not ...
    int max_vis_node_2 = -1;

    double average_vis_prob = 0.0;
    double median_vis_prob = 0.0;

    double stdev_vis_prob = 0.0; // standard deviation
};

static ExposureStats compute_exposure_stats(
    const vector<ArrivedPacket> &arrived_packets,
    int src,
    int tgt,
    int node_count)
{
    ExposureStats stats;
    if (arrived_packets.empty() || node_count <= 2)
        return stats;

    vector<int> seen_count(node_count, 0);
    vector<char> seen(node_count, 0);

    for (const auto &pkt : arrived_packets)
    {
        fill(seen.begin(), seen.end(), 0);
        for (int node : pkt.history)
        {
            if (node == src || node == tgt)
                continue;
            if (!seen[node])
            {
                seen[node] = 1;
                seen_count[node]++;
            }
        }
    }

    vector<pair<double, int>> probs_with_node;
    probs_with_node.reserve(static_cast<size_t>(max(0, node_count - 2)));

    for (int node = 0; node < node_count; node++)
    {
        if (node == src || node == tgt)
            continue;
        const double p = static_cast<double>(seen_count[node]) /
                         static_cast<double>(arrived_packets.size());
        probs_with_node.emplace_back(p, node);
    }

    if (probs_with_node.empty())
        return stats;

    sort(probs_with_node.begin(), probs_with_node.end(),
         [](const auto &a, const auto &b)
         {
             if (a.first != b.first)
                 return a.first > b.first;
             return a.second < b.second;
         });

    stats.max_vis_prob = probs_with_node[0].first;
    stats.max_vis_node = probs_with_node[0].second;
    for (size_t i = 1; i < probs_with_node.size(); i++)
    {
        if (probs_with_node[i].second != stats.max_vis_node)
        {
            stats.max_vis_prob_2 = probs_with_node[i].first;
            stats.max_vis_node_2 = probs_with_node[i].second;
            break;
        }
    }

    vector<double> probs;
    probs.reserve(probs_with_node.size());
    for (const auto &item : probs_with_node)
        probs.push_back(item.first);

    const double sum = accumulate(probs.begin(), probs.end(), 0.0);
    stats.average_vis_prob = sum / static_cast<double>(probs.size());

    vector<double> sorted_probs = probs;
    sort(sorted_probs.begin(), sorted_probs.end());
    const size_t m = sorted_probs.size();
    if (m % 2 == 1)
    {
        stats.median_vis_prob = sorted_probs[m / 2];
    }
    else
    {
        stats.median_vis_prob = (sorted_probs[m / 2 - 1] + sorted_probs[m / 2]) / 2.0;
    }

    double sq_sum = 0.0;
    for (double p : probs)
    {
        const double d = p - stats.average_vis_prob;
        sq_sum += d * d;
    }
    stats.stdev_vis_prob = sqrt(sq_sum / static_cast<double>(probs.size()));

    return stats;
}

static string exposure_node_name(const Graph &g, int node, double vis_prob)
{
    if (vis_prob <= 0.0)
        return "---";
    if (node < 0 || node >= static_cast<int>(g.node_names.size()))
        return "---";
    return g.node_names[node];
}

static string walk_variant_prefix(RandomWalkVariant walk_variant)
{
    return walk_variant == RandomWalkVariant::R
               ? "r"
               : walk_variant == RandomWalkVariant::NB ? "nb" : "lrv";
}

void write_exposure_csv_header(ofstream &out, RandomWalkVariant walk_variant)
{
    const string header_prefix = walk_variant_prefix(walk_variant);
    out << "source,target";
    vector<string> headers = {
        "max_vis_prob",
        "max_vis_node",
        "max_vis_prob_2",
        "max_vis_node_2",
        "average_vis_prob",
        "median_vis_prob",
        "stdev_vis_prob"};
    for (const string &header : headers)
        out << "," << header_prefix << "_" << header;
    for (const string &header : headers)
        out << "," << header_prefix << "_" << header << "_rev";
    out << "\n";
}

void write_exposure_csv(
    ofstream &out,
    const Graph &g,
    size_t src,
    size_t tgt,
    const vector<ArrivedPacket> &arrived_packets,
    const vector<ArrivedPacket> &arrived_packets_rev)
{
    auto exposure_stats = compute_exposure_stats(
        arrived_packets,
        static_cast<int>(src),
        static_cast<int>(tgt),
        static_cast<int>(g.adj.size()));
    auto exposure_stats_rev = compute_exposure_stats(
        arrived_packets_rev,
        static_cast<int>(tgt),
        static_cast<int>(src),
        static_cast<int>(g.adj.size()));

    out << g.node_names[src] << "," << g.node_names[tgt];
    out << "," << fmt_3dp(exposure_stats.max_vis_prob)
        << "," << exposure_node_name(g, exposure_stats.max_vis_node, exposure_stats.max_vis_prob)
        << "," << fmt_3dp(exposure_stats.max_vis_prob_2)
        << "," << exposure_node_name(g, exposure_stats.max_vis_node_2, exposure_stats.max_vis_prob_2)
        << "," << fmt_3dp(exposure_stats.average_vis_prob)
        << "," << fmt_3dp(exposure_stats.median_vis_prob)
        << "," << fmt_3dp(exposure_stats.stdev_vis_prob);
    out << "," << fmt_3dp(exposure_stats_rev.max_vis_prob)
        << "," << exposure_node_name(g, exposure_stats_rev.max_vis_node, exposure_stats_rev.max_vis_prob)
        << "," << fmt_3dp(exposure_stats_rev.max_vis_prob_2)
        << "," << exposure_node_name(g, exposure_stats_rev.max_vis_node_2, exposure_stats_rev.max_vis_prob_2)
        << "," << fmt_3dp(exposure_stats_rev.average_vis_prob)
        << "," << fmt_3dp(exposure_stats_rev.median_vis_prob)
        << "," << fmt_3dp(exposure_stats_rev.stdev_vis_prob);
    out << "\n";
}

void write_hops_csv_header(ofstream &out, RandomWalkVariant walk_variant)
{
    const string header_prefix = walk_variant_prefix(walk_variant);
    out << "source,target";
    vector<string> headers = {"min_hops", "max_hops", "mean_hops", "q1_hops", "q2_hops", "q3_hops"};
    for (const string &header : headers)
        out << "," << header_prefix << "_" << header;
    for (const string &header : headers)
        out << "," << header_prefix << "_" << header << "_rev";
    out << "\n";
}

void write_hops_csv(
    ofstream &out,
    const Graph &g,
    size_t src,
    size_t tgt,
    const vector<ArrivedPacket> &arrived_packets,
    const vector<ArrivedPacket> &arrived_packets_rev)
{
    auto hop_stats = compute_hop_stats(arrived_packets);
    auto hop_stats_rev = compute_hop_stats(arrived_packets_rev);
    out << g.node_names[src] << "," << g.node_names[tgt];
    out << "," << hop_stats.min_hops
        << "," << hop_stats.max_hops
        << "," << fmt_3dp(hop_stats.mean_hops)
        << "," << hop_stats.q1_hops
        << "," << hop_stats.q2_hops
        << "," << hop_stats.q3_hops;
    out << "," << hop_stats_rev.min_hops
        << "," << hop_stats_rev.max_hops
        << "," << fmt_3dp(hop_stats_rev.mean_hops)
        << "," << hop_stats_rev.q1_hops
        << "," << hop_stats_rev.q2_hops
        << "," << hop_stats_rev.q3_hops;
    out << "\n";
}

void write_throughput_csv_header(ofstream &out, RandomWalkVariant walk_variant)
{
    const string header_prefix = walk_variant_prefix(walk_variant);
    out << "source,target," << header_prefix << "_throughput," << header_prefix << "_throughput_rev\n";
}

void write_throughput_csv(
    ofstream &out,
    const Graph &g,
    size_t src,
    size_t tgt,
    const vector<ArrivedPacket> &arrived_packets,
    const vector<ArrivedPacket> &arrived_packets_rev)
{
    const double throughput = compute_throughput(arrived_packets);
    const double throughput_rev = compute_throughput(arrived_packets_rev);
    out << g.node_names[src] << "," << g.node_names[tgt]
        << "," << fmt_3dp(throughput)
        << "," << fmt_3dp(throughput_rev) << "\n";
}

int main(int argc, char **argv)
{
    try
    {
        if (argc < 4)
        {
            cerr << "Usage: " << argv[0] << " <walk_variant:{R,NB,LRV}> <edge_list.csv> <out_dir>\n";
            return 2;
        }

        RANDOM_WALK_VARIANT = parse_walk_variant(argv[1]);
        const string edges_path = argv[2];
        const string out_dir = argv[3];
        auto g = to_graph(load_edges_csv(edges_path));
        fs::create_directories(out_dir);
        ofstream out_exposure(out_dir + "/exposure.csv");
        ofstream out_hops(out_dir + "/hops.csv");
        ofstream out_throughput(out_dir + "/throughput.csv");
        assert(out_exposure);
        assert(out_hops);
        assert(out_throughput);
        write_exposure_csv_header(out_exposure, RANDOM_WALK_VARIANT);
        write_hops_csv_header(out_hops, RANDOM_WALK_VARIANT);
        write_throughput_csv_header(out_throughput, RANDOM_WALK_VARIANT);

        int total_pairs = static_cast<int>(g.adj.size() * (g.adj.size() - 1) / 2);
        int processed_pairs = 0;
        for (size_t src = 0; src < g.adj.size(); src++)
        {
            for (size_t tgt = 0; tgt < g.adj.size(); tgt++)
            {
                if (g.node_names[src] >= g.node_names[tgt])
                    continue;

                auto arrived_packets = run_simulation(g, static_cast<int>(src), static_cast<int>(tgt));
                auto arrived_packets_rev = run_simulation(g, static_cast<int>(tgt), static_cast<int>(src));

                write_exposure_csv(out_exposure, g, src, tgt, arrived_packets, arrived_packets_rev);
                write_hops_csv(out_hops, g, src, tgt, arrived_packets, arrived_packets_rev);
                write_throughput_csv(out_throughput, g, src, tgt, arrived_packets, arrived_packets_rev);

                processed_pairs++;
                cout << "Processed " << processed_pairs << "/" << total_pairs << " pairs\r";
                cout.flush();
            }
        }
        cout << endl;
        cout << "Wrote " << out_dir << "/exposure.csv" << endl;
        cout << "Wrote " << out_dir << "/hops.csv" << endl;
        cout << "Wrote " << out_dir << "/throughput.csv" << endl;
        return 0;
    }
    catch (const exception &e)
    {
        cerr << "Fatal error: " << e.what() << "\n";
        return 1;
    }
}
