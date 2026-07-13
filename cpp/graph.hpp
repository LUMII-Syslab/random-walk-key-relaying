#pragma once

#include <algorithm>
#include <cctype>
#include <fstream>
#include <istream>
#include <limits>
#include <map>
#include <queue>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <set>
#include <vector>

using namespace std;

namespace graph_flow {
struct Edge {
    int to = -1;
    int rev = -1;
    int cap = 0;
};

class Dinic {
public:
    explicit Dinic(int n) : g_(n), level_(n), ptr_(n) {}

    void add_edge(int from, int to, int cap) {
        Edge fwd{to, static_cast<int>(g_[to].size()), cap};
        Edge rev{from, static_cast<int>(g_[from].size()), 0};
        g_[from].push_back(fwd);
        g_[to].push_back(rev);
    }

    int max_flow(int source, int sink) {
        int flow = 0;
        const int inf = numeric_limits<int>::max();
        while (bfs(source, sink)) {
            fill(ptr_.begin(), ptr_.end(), 0);
            while (true) {
                const int pushed = dfs(source, sink, inf);
                if (pushed == 0) break;
                flow += pushed;
            }
        }
        return flow;
    }

private:
    vector<vector<Edge>> g_;
    vector<int> level_;
    vector<int> ptr_;

    bool bfs(int source, int sink) {
        fill(level_.begin(), level_.end(), -1);
        queue<int> q;
        level_[source] = 0;
        q.push(source);
        while (!q.empty()) {
            const int v = q.front();
            q.pop();
            for (const Edge &e : g_[v]) {
                if (e.cap > 0 && level_[e.to] < 0) {
                    level_[e.to] = level_[v] + 1;
                    q.push(e.to);
                }
            }
        }
        return level_[sink] >= 0;
    }

    int dfs(int v, int sink, int pushed) {
        if (pushed == 0 || v == sink) return pushed;
        for (int &i = ptr_[v]; i < static_cast<int>(g_[v].size()); i++) {
            Edge &e = g_[v][i];
            if (e.cap <= 0 || level_[e.to] != level_[v] + 1) continue;
            const int tr = dfs(e.to, sink, min(pushed, e.cap));
            if (tr == 0) continue;
            e.cap -= tr;
            g_[e.to][e.rev].cap += tr;
            return tr;
        }
        return 0;
    }
};
} // namespace graph_flow

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

    /** Local vertex connectivity kappa(s,t) via split-vertex max flow. */
    int vertex_connectivity(int s, int t, const set<EdgeKey> &edges) const {
        const int n = node_count();
        if (s < 0 || s >= n || t < 0 || t >= n) {
            throw runtime_error("vertex_connectivity: node index out of range");
        }
        if (s == t) return 0;

        vector<int> fin(n, -1);
        vector<int> fout(n, -1);
        int next_id = n;
        for (int v = 0; v < n; v++) {
            if (v == s || v == t) continue;
            fin[v] = next_id++;
            fout[v] = next_id++;
        }

        graph_flow::Dinic flow(next_id);
        for (int v = 0; v < n; v++) {
            if (v == s || v == t) continue;
            flow.add_edge(fin[v], fout[v], 1);
        }

        auto out_id = [&](int v) {
            return (v == s || v == t) ? v : fout[v];
        };
        auto in_id = [&](int v) {
            return (v == s || v == t) ? v : fin[v];
        };

        for (const EdgeKey &ek : edges) {
            const int u = ek.u;
            const int v = ek.v;
            if (u < 0 || u >= n || v < 0 || v >= n) {
                throw runtime_error("vertex_connectivity: edge node index out of range");
            }
            flow.add_edge(out_id(u), in_id(v), 1);
            flow.add_edge(out_id(v), in_id(u), 1);
        }

        return flow.max_flow(s, t);
    }

    int vertex_connectivity(int s, int t) const {
        return vertex_connectivity(s, t, edges_);
    }
};
