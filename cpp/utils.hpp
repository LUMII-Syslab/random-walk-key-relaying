#pragma once

#include <algorithm>
#include <cctype>
#include <fstream>
#include <istream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
#include <iomanip>
#include <random>

using namespace std;

class Graph {
    vector<vector<int>> adj_;
    vector<string> idx_to_name_;
    unordered_map<string, int> name_to_idx_;

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
        adj_[u].push_back(v);
        adj_[v].push_back(u);
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

        string line;
        bool first_line = true;
        while (getline(in, line)) {
            if (!line.empty() && line.back() == '\r') line.pop_back();
            if (line.empty()) continue;

            stringstream ss(line);
            string source, target;
            if (!getline(ss, source, ',')) continue;
            if (!getline(ss, target, ',')) continue;
            source = trim(source);
            target = trim(target);
            if (source.empty() || target.empty()) continue;

            if (first_line) {
                string src_l = lower_copy(source);
                string tgt_l = lower_copy(target);
                if (src_l == "source" && tgt_l == "target") {
                    first_line = false;
                    continue;
                }
            }
            first_line = false;
            add_undirected_edge(source, target);
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
};


inline string fmt_2dp(double t)
{
    // "at most two digits after decimal": print 2dp then trim trailing
    // zeros/dot.
    ostringstream oss;
    oss.setf(ios::fixed);
    oss << setprecision(2) << t;
    string s = oss.str();
    // trim trailing zeros
    while (!s.empty() && s.back() == '0')
        s.pop_back();
    if (!s.empty() && s.back() == '.')
        s.pop_back();
    return s;
};

inline string fmt_3dp(double t)
{
    ostringstream oss;
    oss.setf(ios::fixed);
    oss << setprecision(3) << t;
    string s = oss.str();
    return s;
}

int choose_uniformly(const vector<int> &choices, mt19937 &rng){
    int idx = rng() % choices.size();
    return choices[idx];
}