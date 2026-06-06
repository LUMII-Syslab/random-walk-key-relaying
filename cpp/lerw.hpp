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

inline void sample_loop_erased_path(
    WalkSampleScratch &scratch,
    vector<int> &out,
    const vector<vector<int>> &adj,
    RwVariant variant,
    int src_idx,
    int tgt_idx,
    int seed,
    int node_count,
    int max_steps = 100000
) {
    sample_random_walk_history(scratch, adj, variant, src_idx, tgt_idx, seed, node_count, max_steps);
    out = erase_loops_from_history(scratch.history);
    if (out.size() < 2) {
        throw runtime_error("Loop-erased path must contain at least one hop");
    }
    if (out.front() != src_idx || out.back() != tgt_idx) {
        throw runtime_error("Loop-erased path has invalid endpoints");
    }
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
    const RwVariant variant = parse_rw_variant(rw_variant);
    if (variant == RwVariant::Unknown) {
        throw runtime_error("Unknown random walk variant: " + rw_variant);
    }
    WalkSampleScratch scratch;
    scratch.prepare_buffers(node_count);
    vector<int> out;
    sample_loop_erased_path(scratch, out, adj, variant, src_idx, tgt_idx, seed, node_count, max_steps);
    return out;
}
