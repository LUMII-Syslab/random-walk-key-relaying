#pragma once

#include <algorithm>
#include <boost/dynamic_bitset.hpp>
#include <vector>

using namespace std;

namespace cartel {
struct Result {
    int max_seen = 0;
    vector<int> nodes;
};

inline Result worst_case_coverage(
    const vector<boost::dynamic_bitset<>> &covered_chunks_by_node,
    int src,
    int tgt,
    int cartel_sz
) {
    Result res;
    if (cartel_sz <= 0) return res;
    cartel_sz = min(cartel_sz, 3);

    const int n = static_cast<int>(covered_chunks_by_node.size());
    if (n == 0) return res;

    vector<int> candidates;
    candidates.reserve(n);
    for (int v = 0; v < n; v++) {
        if (v == src || v == tgt) continue;
        if (covered_chunks_by_node[v].none()) continue;
        candidates.push_back(v);
    }
    if (candidates.empty()) return res;
    if (static_cast<int>(candidates.size()) < cartel_sz) cartel_sz = static_cast<int>(candidates.size());
    if (cartel_sz <= 0) return res;

    auto coverage1 = [&](int a) -> int {
        return static_cast<int>(covered_chunks_by_node[a].count());
    };
    auto coverage2 = [&](int a, int b) -> int {
        boost::dynamic_bitset<> tmp = covered_chunks_by_node[a];
        tmp |= covered_chunks_by_node[b];
        return static_cast<int>(tmp.count());
    };
    auto coverage3 = [&](int a, int b, int c) -> int {
        boost::dynamic_bitset<> tmp = covered_chunks_by_node[a];
        tmp |= covered_chunks_by_node[b];
        tmp |= covered_chunks_by_node[c];
        return static_cast<int>(tmp.count());
    };

    if (cartel_sz == 1) {
        int best_v = -1;
        int best = 0;
        for (int v : candidates) {
            int cov = coverage1(v);
            if (cov > best) {
                best = cov;
                best_v = v;
            }
        }
        res.max_seen = best;
        if (best_v != -1) res.nodes = {best_v};
        return res;
    }

    if (cartel_sz == 2) {
        int best_a = -1, best_b = -1;
        int best = 0;
        for (size_t i = 0; i < candidates.size(); i++) {
            for (size_t j = i + 1; j < candidates.size(); j++) {
                int a = candidates[i], b = candidates[j];
                int cov = coverage2(a, b);
                if (cov > best) {
                    best = cov;
                    best_a = a;
                    best_b = b;
                }
            }
        }
        res.max_seen = best;
        if (best_a != -1) res.nodes = {best_a, best_b};
        return res;
    }

    int best_a = -1, best_b = -1, best_c = -1;
    int best = 0;
    for (size_t i = 0; i < candidates.size(); i++) {
        for (size_t j = i + 1; j < candidates.size(); j++) {
            for (size_t k = j + 1; k < candidates.size(); k++) {
                int a = candidates[i], b = candidates[j], c = candidates[k];
                int cov = coverage3(a, b, c);
                if (cov > best) {
                    best = cov;
                    best_a = a;
                    best_b = b;
                    best_c = c;
                }
            }
        }
    }
    res.max_seen = best;
    if (best_a != -1) res.nodes = {best_a, best_b, best_c};
    return res;
}
} // namespace cartel

