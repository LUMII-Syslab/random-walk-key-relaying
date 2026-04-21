#pragma once

#include <algorithm>
#include <cctype>
#include <fstream>
#include <istream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <set>
#include <vector>

using namespace std;

struct EdgeKey {
    int u = -1;
    int v = -1;

    EdgeKey() = default;
    EdgeKey(int a, int b) {
        u = min(a, b);
        v = max(a, b);
    }
};

inline bool operator<(const EdgeKey &a, const EdgeKey &b) {
    if (a.u != b.u) return a.u < b.u;
    return a.v < b.v;
}

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

class Graph {
    vector<vector<int>> adj_;
    vector<string> idx_to_name_;
    unordered_map<string, int> name_to_idx_;
    set<EdgeKey> edges_;
    map<EdgeKey, int> edge_vconn_;

    static string trim(string s) {
        while (!s.empty() && isspace(static_cast<unsigned char>(s.back()))) s.pop_back();
        size_t i = 0;
        while (i < s.size() && isspace(static_cast<unsigned char>(s[i]))) i++;
        return s.substr(i);
    }

    static string lower_copy(string s) {
        transform(s.begin(), s.end(), s.begin(), [](unsigned char c) {
            return static_cast<char>(tolower(c));
        });
        return s;
    }

    int resolve_or_add_node(const string &node_name) {
        auto it = name_to_idx_.find(node_name);
        if (it != name_to_idx_.end()) return it->second;
        int idx = static_cast<int>(idx_to_name_.size());
        name_to_idx_[node_name] = idx;
        idx_to_name_.push_back(node_name);
        if (adj_.size() < idx_to_name_.size()) adj_.resize(idx_to_name_.size());
        return idx;
    }

    void add_undirected_edge(const string &u_name, const string &v_name) {
        int u = resolve_or_add_node(u_name);
        int v = resolve_or_add_node(v_name);
        if (u == v) throw runtime_error("Self-loop edge is not allowed: " + u_name);
        EdgeKey ek(u, v);
        if (edges_.count(ek) > 0) return; // ignore duplicate edges
        edges_.insert(ek);
        adj_[u].push_back(v);
        adj_[v].push_back(u);
    }

    void set_edge_vconn(int u, int v, int vconn) {
        EdgeKey ek(u, v);
        auto it = edge_vconn_.find(ek);
        if (it == edge_vconn_.end()) {
            edge_vconn_[ek] = vconn;
        } else {
            // Keep the first value for duplicate edges (consistent with add_undirected_edge behavior).
        }
    }

    void read_from_stdin(istream &in) {
        int n, m;
        if (!(in >> n >> m)) {
            throw runtime_error("Failed to read graph size from stdin (expected: n m)");
        }
        if (n < 0 || m < 0) {
            throw runtime_error("Invalid graph size from stdin");
        }

        adj_.assign(n, {});
        idx_to_name_.clear();
        name_to_idx_.clear();
        edges_.clear();
        edge_vconn_.clear();

        for (int i = 0; i < m; i++) {
            string u_name, v_name;
            if (!(in >> u_name >> v_name)) {
                throw runtime_error("Failed to read edge from stdin at index " + to_string(i));
            }
            add_undirected_edge(u_name, v_name);
            if (static_cast<int>(idx_to_name_.size()) > n) {
                throw runtime_error("More unique node names than declared n in stdin input");
            }
        }
    }

    void read_from_csv_file(const string &edges_csv_path) {
        ifstream in(edges_csv_path);
        if (!in.is_open()) {
            throw runtime_error("Cannot open CSV file: " + edges_csv_path);
        }

        adj_.clear();
        idx_to_name_.clear();
        name_to_idx_.clear();
        edges_.clear();
        edge_vconn_.clear();

        string line;
        bool first_line = true;
        int vconn_col = -1;
        while (getline(in, line)) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            if (line.empty()) continue;

            stringstream ss(line);
            vector<string> cols;
            string cell;
            while (getline(ss, cell, ',')) cols.push_back(trim(cell));
            if (cols.size() < 2) continue;

            string source = cols[0];
            string target = cols[1];
            if (source.empty() || target.empty()) continue;

            if (first_line) {
                // Header detection + column discovery (case-insensitive).
                vector<string> headers_l;
                headers_l.reserve(cols.size());
                for (const string &h : cols) headers_l.push_back(lower_copy(h));

                // Only treat as header if it looks like one.
                if (headers_l[0] == "source" && headers_l[1] == "target") {
                    for (int i = 0; i < static_cast<int>(headers_l.size()); i++) {
                        if (headers_l[i] == "vconn") vconn_col = i;
                    }
                    first_line = false;
                    continue;
                }
            }
            first_line = false;
            add_undirected_edge(source, target);
            if (vconn_col != -1 && vconn_col < static_cast<int>(cols.size())) {
                const string &vconn_s = cols[vconn_col];
                if (!vconn_s.empty()) {
                    try {
                        int vconn = stoi(vconn_s);
                        int u = node_index(source);
                        int v = node_index(target);
                        set_edge_vconn(u, v, vconn);
                    } catch (...) {
                        // Ignore malformed VConn values.
                    }
                }
            }
        }
    }

public:
    Graph() = default;

    explicit Graph(istream &in) {
        read_from_stdin(in);
    }

    explicit Graph(const string &edges_csv_path) {
        read_from_csv_file(edges_csv_path);
    }

    const vector<vector<int>> &adj_list() const {
        return adj_;
    }

    int node_count() const {
        return static_cast<int>(adj_.size());
    }

    const set<EdgeKey> &edges() const {
        return edges_;
    }

    /** Per-link precomputed VConn from `edges.csv` (defaults to 1 if missing). */
    int edge_vconn(int a, int b) const {
        auto it = edge_vconn_.find(EdgeKey(a, b));
        if (it == edge_vconn_.end()) return 1;
        return it->second;
    }

    int node_index(const string &node_name) const {
        auto it = name_to_idx_.find(node_name);
        if (it == name_to_idx_.end()) {
            throw runtime_error("Unknown node name: " + node_name);
        }
        return it->second;
    }

    const string &node_name(int node_idx) const {
        if (node_idx < 0 || node_idx >= static_cast<int>(idx_to_name_.size())) {
            throw runtime_error("Node index out of range: " + to_string(node_idx));
        }
        return idx_to_name_[node_idx];
    }

    vector<int> neighbors(int node_idx) const {
        return adj_[node_idx];
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
