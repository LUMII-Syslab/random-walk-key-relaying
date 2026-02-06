// Small helper utilities for simulate.cpp (no external libraries).
#pragma once

#include <cctype>
#include <string>
#include <unordered_map>
#include <vector>

inline std::string trim(const std::string& s) {
    size_t i = 0;
    while (i < s.size() && std::isspace(static_cast<unsigned char>(s[i]))) i++;
    size_t j = s.size();
    while (j > i && std::isspace(static_cast<unsigned char>(s[j - 1]))) j--;
    return s.substr(i, j - i);
}

inline std::vector<std::string> split_csv_line(const std::string& line) {
    // Minimal CSV splitter (no multiline fields). Handles quotes and doubled quotes.
    std::vector<std::string> out;
    std::string cur;
    bool in_quotes = false;
    for (size_t i = 0; i < line.size(); i++) {
        char c = line[i];
        if (c == '"') {
            if (in_quotes && i + 1 < line.size() && line[i + 1] == '"') {
                cur.push_back('"');
                i++;
            } else {
                in_quotes = !in_quotes;
            }
        } else if (c == ',' && !in_quotes) {
            out.push_back(trim(cur));
            cur.clear();
        } else {
            cur.push_back(c);
        }
    }
    out.push_back(trim(cur));
    return out;
}

inline int get_or_add_node(
    const std::string& name,
    std::unordered_map<std::string, int>& idx,
    std::vector<std::string>& names
) {
    auto it = idx.find(name);
    if (it != idx.end()) return it->second;
    int id = static_cast<int>(names.size());
    idx.emplace(name, id);
    names.push_back(name);
    return id;
}


