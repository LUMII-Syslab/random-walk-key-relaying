#pragma once

#include <algorithm>
#include <cctype>
#include <string>
#include <string_view>

using namespace std;

/** Paths are relative to the `cpp/` working directory (same layout as `graphs/` in the repo). */
inline string lower_ascii(string s) {
    transform(s.begin(), s.end(), s.begin(), [](unsigned char c) {
        return static_cast<char>(tolower(c));
    });
    return s;
}

inline const char *named_graph_edges_csv(string_view name) {
    const string key = lower_ascii(string(name));
    if (key == "nsfnet") {
        return "../graphs/nsfnet/edges.csv";
    }
    if (key == "geant") {
        return "../graphs/geant/edges.csv";
    }
    if (key == "hexagon") {
        return "../graphs/hexagon/edges.csv";
    }
    return nullptr;
}

/** Named topology (nsfnet, geant) or a path to an edges CSV file. */
inline string resolve_graph_spec(string_view spec) {
    const char *builtin = named_graph_edges_csv(spec);
    if (builtin != nullptr) {
        return builtin;
    }
    return string(spec);
}
