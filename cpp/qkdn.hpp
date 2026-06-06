#pragma once

#include <istream>
#include <map>
#include <stdexcept>
#include <string>

#include "graph.hpp"

using namespace std;

/** Per-link QKD buffer model; `reserve` matches cpp/tput.cpp semantics. */
struct LinkState {
    double bit_balance = 0.0;
    double last_request = 0.0;

    /** Returns waiting time in seconds. */
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

/**
 * QKD overlay for a (static) undirected graph: maintains per-link `LinkState`
 * used to compute waiting times for OTP availability.
 *
 * Owns a `Graph` (composition) and a map from edges to mutable link state.
 */
class QkdNetwork {
    Graph graph_;
    map<EdgeKey, LinkState> link_states_;

    void init_link_states_from_graph_edges() {
        link_states_.clear();
        for (const EdgeKey &e : graph_.edges()) {
            link_states_.emplace(e, LinkState{});
        }
    }

public:
    QkdNetwork() = default;

    explicit QkdNetwork(Graph graph) : graph_(std::move(graph)) {
        init_link_states_from_graph_edges();
    }

    explicit QkdNetwork(istream &in) : graph_(in) {
        init_link_states_from_graph_edges();
    }

    explicit QkdNetwork(const string &edges_csv_path) : graph_(edges_csv_path) {
        init_link_states_from_graph_edges();
    }

    const Graph &graph() const { return graph_; }
    Graph &graph() { return graph_; }

    const vector<vector<int>> &adj_list() const { return graph_.adj_list(); }
    int node_count() const { return graph_.node_count(); }
    int node_index(const string &node_name) const { return graph_.node_index(node_name); }
    const string &node_name(int node_idx) const { return graph_.node_name(node_idx); }

    /** Mutable state for the undirected edge between `a` and `b` (order-independent). */
    LinkState &link_state(int a, int b) {
        auto it = link_states_.find(EdgeKey(a, b));
        if (it == link_states_.end()) {
            throw runtime_error("link_state: not an edge between nodes");
        }
        return it->second;
    }

    const LinkState &link_state(int a, int b) const {
        auto it = link_states_.find(EdgeKey(a, b));
        if (it == link_states_.end()) {
            throw runtime_error("link_state: not an edge between nodes");
        }
        return it->second;
    }
};
