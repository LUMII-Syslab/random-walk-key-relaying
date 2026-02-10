// Small helper utilities for simulate.cpp (no external libraries).
#pragma once

using namespace std;

#include <cctype>
#include <string>
#include <unordered_map>
#include <vector>
#include <algorithm>
#include <cassert>
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
#include <utility>

inline string trim(const string &s)
{
    size_t i = 0;
    while (i < s.size() && isspace(static_cast<unsigned char>(s[i])))
        i++;
    size_t j = s.size();
    while (j > i && isspace(static_cast<unsigned char>(s[j - 1])))
        j--;
    return s.substr(i, j - i);
}

inline vector<string> split_csv_line(const string &line)
{
    // Minimal CSV splitter (no multiline fields). Handles quotes and doubled quotes.
    vector<string> out;
    string cur;
    bool in_quotes = false;
    for (size_t i = 0; i < line.size(); i++)
    {
        char c = line[i];
        if (c == '"')
        {
            if (in_quotes && i + 1 < line.size() && line[i + 1] == '"')
            {
                cur.push_back('"');
                i++;
            }
            else
            {
                in_quotes = !in_quotes;
            }
        }
        else if (c == ',' && !in_quotes)
        {
            out.push_back(trim(cur));
            cur.clear();
        }
        else
        {
            cur.push_back(c);
        }
    }
    out.push_back(trim(cur));
    return out;
}

inline int get_or_add_node(
    const string &name,
    unordered_map<string, int> &idx,
    vector<string> &names)
{
    auto it = idx.find(name);
    if (it != idx.end())
        return it->second;
    int id = static_cast<int>(names.size());
    idx.emplace(name, id);
    names.push_back(name);
    return id;
}

static double clamp01(double x)
{
    if (x < 0.0)
        return 0.0;
    if (x > 1.0)
        return 1.0;
    return x;
}

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

struct EdgesCsvGraph{
    vector<string> node_names;
    vector<vector<int>> adj;
};

static EdgesCsvGraph load_edges_csv(const string &edges_path)
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

    return EdgesCsvGraph{move(node_names), move(adj)};
}

static string to_upper_ascii(string s)
{
    for (char &c : s)
        c = static_cast<char>(toupper(static_cast<unsigned char>(c)));
    return s;
}