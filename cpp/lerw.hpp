#pragma once

#include <memory>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

#include "walk.hpp"

using namespace std;

inline unique_ptr<RwToken> make_rw_token(
    const string &rw_variant,
    int src_idx,
    int tgt_idx,
    int seed,
    int node_count
) {
    if (rw_variant == "R") return make_unique<RToken>(src_idx, tgt_idx, seed);
    if (rw_variant == "NB") return make_unique<NbToken>(src_idx, tgt_idx, seed);
    if (rw_variant == "LRV") return make_unique<LrvToken>(src_idx, tgt_idx, seed);
    if (rw_variant == "NC") return make_unique<NcToken>(src_idx, tgt_idx, seed, node_count);
    if (rw_variant == "HS") return make_unique<HsToken>(src_idx, tgt_idx, seed);
    return nullptr;
}

inline vector<int> erase_loops_from_history(const vector<int> &history) {
    vector<int> loop_erased_history;
    loop_erased_history.reserve(history.size());
    unordered_map<int, size_t> first_pos;
    for (int node : history) {
        auto it = first_pos.find(node);
        if (it == first_pos.end()) {
            first_pos[node] = loop_erased_history.size();
            loop_erased_history.push_back(node);
            continue;
        }

        size_t keep_until = it->second;
        for (size_t idx = keep_until + 1; idx < loop_erased_history.size(); idx++) {
            first_pos.erase(loop_erased_history[idx]);
        }
        loop_erased_history.resize(keep_until + 1);
    }
    return loop_erased_history;
}

inline vector<int> sample_random_walk_history(
    const vector<vector<int>> &adj,
    RwToken &token,
    int src_idx,
    int tgt_idx,
    int max_steps = 100000
) {
    int position = src_idx;
    vector<int> history = {src_idx};
    int hops = 0;
    while (position != tgt_idx) {
        int next = token.choose_next_and_update(position, adj[position]);
        position = next;
        history.push_back(position);
        if (++hops > max_steps) {
            throw runtime_error("Random walk exceeded " + to_string(max_steps) + " steps");
        }
    }
    return history;
}

inline vector<int> sample_loop_erased_path(
    const vector<vector<int>> &adj,
    const string &rw_variant,
    int src_idx,
    int tgt_idx,
    int seed,
    int node_count,
    int max_steps = 100000
) {
    unique_ptr<RwToken> token = make_rw_token(rw_variant, src_idx, tgt_idx, seed, node_count);
    if (!token) {
        throw runtime_error("Unknown random walk variant: " + rw_variant);
    }

    vector<int> loop_erased_path = erase_loops_from_history(
        sample_random_walk_history(adj, *token, src_idx, tgt_idx, max_steps)
    );
    if (loop_erased_path.size() < 2) {
        throw runtime_error("Loop-erased path must contain at least one hop");
    }
    if (loop_erased_path.front() != src_idx || loop_erased_path.back() != tgt_idx) {
        throw runtime_error("Loop-erased path has invalid endpoints");
    }
    return loop_erased_path;
}
