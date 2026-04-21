#pragma once

#include <algorithm>
#include <cctype>
#include <fstream>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include "graph.hpp"

using namespace std;

namespace pair_vconn {
inline string trim_copy(string s) {
    while (!s.empty() && isspace(static_cast<unsigned char>(s.back()))) s.pop_back();
    size_t i = 0;
    while (i < s.size() && isspace(static_cast<unsigned char>(s[i]))) i++;
    return s.substr(i);
}

inline string lower_copy(string s) {
    transform(s.begin(), s.end(), s.begin(), [](unsigned char c) {
        return static_cast<char>(tolower(c));
    });
    return s;
}

inline vector<string> parse_csv_line(const string &ln) {
    string s = ln;
    if (!s.empty() && s.back() == '\r') s.pop_back();
    stringstream ss(s);
    vector<string> cols;
    string cell;
    while (getline(ss, cell, ',')) cols.push_back(trim_copy(cell));
    return cols;
}

/** Load all-pairs VConn table from conn.csv (Source,Target,VConn). */
inline map<pair<int,int>, int> load_conn_csv_or_throw(const Graph &graph, const string &path) {
    ifstream in(path);
    if (!in.is_open()) {
        throw runtime_error("Cannot open v-conn CSV file: " + path);
    }

    string line;
    bool first_line = true;
    int src_col = -1;
    int tgt_col = -1;
    int vconn_col = -1;
    map<pair<int,int>, int> res;

    while (getline(in, line)) {
        if (line.empty()) continue;
        vector<string> cols = parse_csv_line(line);
        if (cols.size() < 3) continue;

        if (first_line) {
            vector<string> headers_l;
            headers_l.reserve(cols.size());
            for (const string &h : cols) headers_l.push_back(lower_copy(h));
            for (int i = 0; i < static_cast<int>(headers_l.size()); i++) {
                if (headers_l[i] == "source") src_col = i;
                else if (headers_l[i] == "target") tgt_col = i;
                else if (headers_l[i] == "vconn") vconn_col = i;
            }
            if (src_col != -1 && tgt_col != -1 && vconn_col != -1) {
                first_line = false;
                continue;
            }
            throw runtime_error("Invalid conn.csv header in " + path + " (expected Source,Target,VConn)");
        }
        first_line = false;

        if (
            src_col >= static_cast<int>(cols.size())
            || tgt_col >= static_cast<int>(cols.size())
            || vconn_col >= static_cast<int>(cols.size())
        ) {
            continue;
        }

        const string &src_name = cols[src_col];
        const string &tgt_name = cols[tgt_col];
        const string &vconn_s = cols[vconn_col];
        if (src_name.empty() || tgt_name.empty() || vconn_s.empty()) continue;

        int vconn = 1;
        try {
            vconn = stoi(vconn_s);
        } catch (...) {
            continue;
        }

        int s = graph.node_index(src_name);
        int t = graph.node_index(tgt_name);
        res[{s, t}] = vconn;
    }

    if (res.empty()) {
        throw runtime_error("Loaded empty conn.csv from " + path);
    }
    return res;
}

inline int lookup_or_throw(
    const Graph &graph,
    const map<pair<int,int>, int> &pair_vconn,
    int src,
    int tgt
) {
    auto it = pair_vconn.find({src, tgt});
    if (it == pair_vconn.end()) it = pair_vconn.find({tgt, src});
    if (it == pair_vconn.end()) {
        throw runtime_error(
            "Missing VConn for pair (" + graph.node_name(src) + "," + graph.node_name(tgt) + ") in conn.csv"
        );
    }
    return it->second;
}
} // namespace pair_vconn

