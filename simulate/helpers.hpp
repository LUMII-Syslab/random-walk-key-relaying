// Small helper utilities for simulate.cpp (no external libraries).
#pragma once

#include <cctype>
#include <string>
#include <unordered_map>
#include <vector>
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

inline std::string trim(const std::string &s)
{
    size_t i = 0;
    while (i < s.size() && std::isspace(static_cast<unsigned char>(s[i])))
        i++;
    size_t j = s.size();
    while (j > i && std::isspace(static_cast<unsigned char>(s[j - 1])))
        j--;
    return s.substr(i, j - i);
}

inline std::vector<std::string> split_csv_line(const std::string &line)
{
    // Minimal CSV splitter (no multiline fields). Handles quotes and doubled quotes.
    std::vector<std::string> out;
    std::string cur;
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
    const std::string &name,
    std::unordered_map<std::string, int> &idx,
    std::vector<std::string> &names)
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

inline std::string fmt_2dp(double t)
{
    // "at most two digits after decimal": print 2dp then trim trailing
    // zeros/dot.
    std::ostringstream oss;
    oss.setf(std::ios::fixed);
    oss << std::setprecision(2) << t;
    std::string s = oss.str();
    // trim trailing zeros
    while (!s.empty() && s.back() == '0')
        s.pop_back();
    if (!s.empty() && s.back() == '.')
        s.pop_back();
    return s;
};