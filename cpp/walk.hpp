#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <map>
#include <random>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>
#include "utils.hpp"
#include <set>
#include <cassert>
using namespace std;

#ifndef RW_DIRECT_TO_VISIBLE_TARGET
#define RW_DIRECT_TO_VISIBLE_TARGET 1
#endif

inline bool has_neighbor(const vector<int> &nbrs, int node_idx) {
    for(int nbr : nbrs){
        if(nbr == node_idx) return true;
    }
    return false;
}

inline void visited_bit_set(vector<uint64_t> &bits, int u) {
    bits[static_cast<size_t>(u) >> 6] |= (uint64_t(1) << (u & 63));
}

inline bool visited_bit_test(const vector<uint64_t> &bits, int u) {
    return (bits[static_cast<size_t>(u) >> 6] >> (u & 63)) & 1;
}

inline uint64_t hs_deterministic_node_score(int node_idx, int walk_seed) {
    seed_seq seq{node_idx, walk_seed};
    array<uint32_t, 2> words{};
    seq.generate(words.begin(), words.end());
    return (static_cast<uint64_t>(words[0]) << 32) | words[1];
}

inline int nc_disabled_node(int src_idx, int tgt_idx, int seed, int node_count) {
    if (node_count <= 0) throw runtime_error("NC walk requires positive node_count");
    int eligible = 0;
    for (int u = 0; u < node_count; u++) {
        if (u == src_idx || u == tgt_idx) continue;
        eligible++;
    }
    if (eligible == 0) return -1;
    int pick = ((seed % eligible) + eligible) % eligible;
    for (int u = 0; u < node_count; u++) {
        if (u == src_idx || u == tgt_idx) continue;
        if (pick-- == 0) return u;
    }
    return -1;
}

struct RwToken{
    virtual int choose_next_and_update(int node_idx, const vector<int> &nbrs) = 0;
};

class FixedPathToken: public RwToken{
    vector<int> path;
    size_t path_pos = 0;
public:
    explicit FixedPathToken(vector<int> fixed_path): path(std::move(fixed_path)){
        if(path.size() < 2) throw runtime_error("Fixed path token requires at least two nodes");
    }

    int choose_next_and_update(int node_idx, const vector<int> &nbrs){
        (void)nbrs;
        if(path_pos >= path.size() - 1) {
            throw runtime_error("Fixed path token exhausted");
        }
        if(node_idx != path[path_pos]) {
            throw runtime_error("Fixed path token used at unexpected node");
        }
        int next = path[path_pos + 1];
        if(!has_neighbor(nbrs, next)) {
            throw runtime_error("Fixed path token contains a non-edge hop");
        }
        path_pos++;
        return next;
    }
};

// simple random walk (R)
class RToken: public RwToken{
    int src_node_idx;
    int tgt_node_idx;
    mt19937 rng;
public:
    RToken(int src, int tgt, int seed): rng(seed){
        this->src_node_idx = src;
        this->tgt_node_idx = tgt;
    }
    int choose_next_and_update(int node_idx, const vector<int> &nbrs){
        (void)node_idx;
#if RW_DIRECT_TO_VISIBLE_TARGET
        if(has_neighbor(nbrs, tgt_node_idx)) return tgt_node_idx;
#endif
        return choose_uniformly(nbrs, rng);
    }
};

// non-backtracking (NB) random walk variant
class NbToken: public RwToken{
    int src_node_idx;
    int tgt_node_idx;
    mt19937 rng;
    int current = -1;
    int previous = -1;
public:
    NbToken(int src, int tgt, int seed): rng(seed){
        this->src_node_idx = src;
        this->tgt_node_idx = tgt;
        current = src_node_idx;
        previous = -1;
    }
    int choose_next_and_update(int node_idx, const vector<int> &nbrs){
        (void)node_idx;
#if RW_DIRECT_TO_VISIBLE_TARGET
        if(has_neighbor(nbrs, tgt_node_idx)) {
            previous = current;
            current = tgt_node_idx;
            return tgt_node_idx;
        }
#endif
        if(nbrs.size()==1) {
            int chosen = nbrs[0];
            previous = current;
            current = chosen;
            return chosen;
        }

        // filter out the previous node
        vector<int> choices;
        for(int nbr: nbrs){
            if(nbr != previous) choices.push_back(nbr);
        }

        int chosen = choose_uniformly(choices, rng);
        previous = current;
        current = chosen;
        return chosen;
    }
};

// least-recently-visited (LRV) random walk variant
class LrvToken: public RwToken{
    int src_node_idx;
    int tgt_node_idx;
    int age; // history length
    map<int,int> last_seen;
    mt19937 rng;

    map<int,int> when_nbrs_last_seen(const vector<int> &nbrs) const {
        map<int,int> nbr_time;
        for(int nbr: nbrs){
            // Unseen neighbors should be preferred over seen ones.
            if(last_seen.count(nbr) == 0) nbr_time[nbr] = -1;
            else nbr_time[nbr] = last_seen.at(nbr);
        }
        return nbr_time;
    }
    void append_to_history(int node_idx){
        age++;
        last_seen[node_idx] = age;
    }
public:
    LrvToken(int src, int tgt, int seed): rng(seed){
        src_node_idx = src;
        tgt_node_idx = tgt;
        age = 0;
        last_seen[src_node_idx]=0;
    }
    int choose_next_and_update(int node_idx, const vector<int> &nbrs){
        (void)node_idx;
#if RW_DIRECT_TO_VISIBLE_TARGET
        if(has_neighbor(nbrs, tgt_node_idx)) {
            append_to_history(tgt_node_idx);
            return tgt_node_idx;
        }
#endif
        if(nbrs.size()==1) {
            int chosen = nbrs[0];
            append_to_history(chosen);
            return chosen;
        }

        // find out when were neighbors last seen or set to 0 if never
        map<int,int> nbr_time = when_nbrs_last_seen(nbrs);

        // find the minimum timestamp among neighbors
        int min_time = numeric_limits<int>::max();
        for(auto [nbr, time]: nbr_time){
            min_time = min(min_time, time);
        }

        // choose uniformly among neighbors with minimum timestamp
        vector<int> choices;
        for(auto [nbr, time]: nbr_time){
            if(time == min_time) choices.push_back(nbr);
        }
        int chosen = choose_uniformly(choices, rng);

        append_to_history(chosen);
        return chosen;
    }
};

// node-coloring (NC) random walk variant
// acts like LRV, but each walk disables one node chosen from seed % node_count
class NcToken: public RwToken{
    int src_node_idx;
    int tgt_node_idx;
    int disabled_node_idx;
    int age; // history length
    map<int,int> last_seen;
    mt19937 rng;

    vector<int> enabled_neighbors(const vector<int> &nbrs) const {
        vector<int> choices;
        for(int nbr : nbrs){
            if(nbr != disabled_node_idx) choices.push_back(nbr);
        }
        return choices;
    }
    map<int,int> when_nbrs_last_seen(const vector<int> &nbrs) const {
        map<int,int> nbr_time;
        for(int nbr: nbrs){
            if(last_seen.count(nbr) == 0) nbr_time[nbr] = -1;
            else nbr_time[nbr] = last_seen.at(nbr);
        }
        return nbr_time;
    }
    void append_to_history(int node_idx){
        age++;
        last_seen[node_idx] = age;
    }
public:
    NcToken(int src, int tgt, int seed, int node_count): rng(seed){
        if(node_count <= 0) throw runtime_error("NC walk requires positive node_count");
        src_node_idx = src;
        tgt_node_idx = tgt;
        vector<int> eligible_disabled_nodes;
        eligible_disabled_nodes.reserve(node_count);
        for(int node_idx = 0; node_idx < node_count; node_idx++){
            if(node_idx == src_node_idx || node_idx == tgt_node_idx) continue;
            eligible_disabled_nodes.push_back(node_idx);
        }
        if(eligible_disabled_nodes.empty()) disabled_node_idx = -1;
        else {
            int disabled_offset = ((seed % static_cast<int>(eligible_disabled_nodes.size()))
                                   + static_cast<int>(eligible_disabled_nodes.size()))
                                  % static_cast<int>(eligible_disabled_nodes.size());
            disabled_node_idx = eligible_disabled_nodes[disabled_offset];
        }
        age = 0;
        last_seen[src_node_idx] = age;
    }
    int choose_next_and_update(int node_idx, const vector<int> &nbrs){
        (void)node_idx;
        vector<int> choices = enabled_neighbors(nbrs);
        if(choices.empty()) {
            throw runtime_error("NC walk reached a node whose only neighbors are disabled");
        }
#if RW_DIRECT_TO_VISIBLE_TARGET
        if(tgt_node_idx != disabled_node_idx && has_neighbor(choices, tgt_node_idx)) {
            append_to_history(tgt_node_idx);
            return tgt_node_idx;
        }
#endif
        if(choices.size() == 1) {
            int chosen = choices[0];
            append_to_history(chosen);
            return chosen;
        }

        map<int,int> nbr_time = when_nbrs_last_seen(choices);
        int min_time = numeric_limits<int>::max();
        for(auto [nbr, time] : nbr_time){
            min_time = min(min_time, time);
        }

        vector<int> lrv_choices;
        for(auto [nbr, time] : nbr_time){
            if(time == min_time) lrv_choices.push_back(nbr);
        }
        int chosen = choose_uniformly(lrv_choices, rng);
        append_to_history(chosen);
        return chosen;
    }
};

// highest-score vertex (HS) random walk variant
// vertex scores are predetermined at the start of the walk
// the intuitive idea is that in one of the many walks
// the "evil" vertex will be assigned a low value and therefore not visited
// 
// if all neighbors have been visited, fall back to non-backtracking
class HsToken: public RwToken{
    int src_node_idx;
    int tgt_node_idx;
    set<int> visited;
    map<int,int> last_visited;
    int age;
    mt19937 rng;
    int walk_seed;
    int previous = -1;
    void append_to_history(int node_idx){
        age++;
        last_visited[node_idx] = age;
    }
    uint64_t deterministic_node_score(int node_idx) const {
        return hs_deterministic_node_score(node_idx, walk_seed);
    }
    uint64_t get_node_score(int node_idx) const {
        if(visited.count(node_idx) > 0) return 0;
        return deterministic_node_score(node_idx);
    }
protected:
    uint64_t base_node_score(int node_idx) const {
        return deterministic_node_score(node_idx);
    }
public:
    HsToken(int src, int tgt, int seed): rng(seed){
        src_node_idx = src;
        tgt_node_idx = tgt;
        walk_seed = seed;
        age = 0;
        visited.insert(src_node_idx);
        last_visited[src_node_idx] = age;
    }
    int choose_next_and_update(int node_idx, const vector<int> &nbrs){
#if RW_DIRECT_TO_VISIBLE_TARGET
        if(has_neighbor(nbrs, tgt_node_idx)) {
            visited.insert(tgt_node_idx);
            append_to_history(tgt_node_idx);
            previous = node_idx;
            return tgt_node_idx;
        }
#endif
        if(nbrs.size()==1) {
            int chosen = nbrs[0];
            visited.insert(chosen);
            append_to_history(chosen);
            previous = node_idx;
            return chosen;
        }

        vector<int> candidate_nbrs;
        for(int nbr: nbrs){
            if(visited.count(nbr) == 0) candidate_nbrs.push_back(nbr);
        }
        if(candidate_nbrs.empty()) {
            for(int nbr: nbrs){
                if(nbr != previous) candidate_nbrs.push_back(nbr);
            }
            if(candidate_nbrs.empty()) candidate_nbrs = nbrs;
        }

        uint64_t max_score = 0;
        vector<int> choices;
        for(int nbr: candidate_nbrs){
            uint64_t score = get_node_score(nbr);
            if(score == max_score) choices.push_back(nbr);
            if(score > max_score) {
                max_score = score;
                choices.clear();
                choices.push_back(nbr);
            }
        }

        int chosen = choose_uniformly(choices, rng);
        visited.insert(chosen);
        append_to_history(chosen);
        previous = node_idx;
        return chosen;
    }

};

enum class RwVariant : uint8_t {
    Unknown = 0,
    R,
    NB,
    LRV,
    NC,
    HS,
};

inline RwVariant parse_rw_variant(string_view rw_variant) {
    if (rw_variant.size() == 1 && rw_variant[0] == 'R') return RwVariant::R;
    if (rw_variant == "NB") return RwVariant::NB;
    if (rw_variant == "LRV") return RwVariant::LRV;
    if (rw_variant == "NC") return RwVariant::NC;
    if (rw_variant == "HS") return RwVariant::HS;
    return RwVariant::Unknown;
}

inline bool is_rw_variant(const string &rw_variant) {
    return parse_rw_variant(rw_variant) != RwVariant::Unknown;
}

// Reusable buffers for Monte Carlo loops (one scratch per thread).
struct WalkSampleScratch {
    vector<int> history;
    vector<int> last_seen;
    vector<uint64_t> visited_bits;
    vector<uint64_t> hs_scores;

    void prepare_buffers(int node_count) {
        if (history.capacity() < 128) {
            history.reserve(128);
        }
        if (static_cast<int>(last_seen.size()) < node_count) {
            last_seen.resize(static_cast<size_t>(node_count));
        }
        const size_t words = (static_cast<size_t>(node_count) + 63) / 64;
        if (visited_bits.size() < words) {
            visited_bits.resize(words);
        }
        if (static_cast<int>(hs_scores.size()) < node_count) {
            hs_scores.resize(static_cast<size_t>(node_count));
        }
    }
};

namespace walk_sample_detail {

inline void throw_step_limit(int max_steps) {
    throw runtime_error("Random walk exceeded " + to_string(max_steps) + " steps");
}

inline int reservoir_pick(int nbr, int &count, int chosen, mt19937 &rng) {
    count++;
    if (count == 1 || (rng() % static_cast<uint32_t>(count)) == 0) {
        return nbr;
    }
    return chosen;
}

#if RW_DIRECT_TO_VISIBLE_TARGET
inline bool pick_visible_target(const vector<int> &nbrs, int tgt_idx, int &next) {
    for (int nbr : nbrs) {
        if (nbr == tgt_idx) {
            next = tgt_idx;
            return true;
        }
    }
    return false;
}
#endif

inline void sample_r(
    vector<int> &history,
    const vector<vector<int>> &adj,
    int src_idx,
    int tgt_idx,
    mt19937 &rng,
    int max_steps
) {
    int position = src_idx;
    int hops = 0;
    while (position != tgt_idx) {
        const vector<int> &nbrs = adj[static_cast<size_t>(position)];
        int next;
#if RW_DIRECT_TO_VISIBLE_TARGET
        if (pick_visible_target(nbrs, tgt_idx, next)) {
            history.push_back(next);
            return;
        }
        next = nbrs[static_cast<size_t>(rng()) % nbrs.size()];
#else
        next = nbrs[static_cast<size_t>(rng()) % nbrs.size()];
#endif
        position = next;
        history.push_back(next);
        if (++hops > max_steps) throw_step_limit(max_steps);
    }
}

inline void sample_nb(
    vector<int> &history,
    const vector<vector<int>> &adj,
    int src_idx,
    int tgt_idx,
    mt19937 &rng,
    int max_steps
) {
    int position = src_idx;
    int previous = -1;
    int hops = 0;
    while (position != tgt_idx) {
        const vector<int> &nbrs = adj[static_cast<size_t>(position)];
        int next;
#if RW_DIRECT_TO_VISIBLE_TARGET
        if (pick_visible_target(nbrs, tgt_idx, next)) {
            history.push_back(next);
            return;
        }
#endif
        if (nbrs.size() == 1) {
            next = nbrs[0];
        } else {
            int count = 0;
            next = nbrs[0];
            for (int nbr : nbrs) {
                if (nbr == previous) continue;
                next = reservoir_pick(nbr, count, next, rng);
            }
        }
        previous = position;
        position = next;
        history.push_back(next);
        if (++hops > max_steps) throw_step_limit(max_steps);
    }
}

inline void sample_lrv(
    vector<int> &history,
    const vector<vector<int>> &adj,
    int src_idx,
    int tgt_idx,
    vector<int> &last_seen,
    mt19937 &rng,
    int max_steps
) {
    fill(last_seen.begin(), last_seen.end(), -1);
    int age = 0;
    last_seen[src_idx] = age;
    int position = src_idx;
    int hops = 0;
    while (position != tgt_idx) {
        const vector<int> &nbrs = adj[static_cast<size_t>(position)];
        int next;
#if RW_DIRECT_TO_VISIBLE_TARGET
        if (pick_visible_target(nbrs, tgt_idx, next)) {
            history.push_back(next);
            return;
        }
#endif
        if (nbrs.size() == 1) {
            next = nbrs[0];
        } else {
            int min_time = numeric_limits<int>::max();
            for (int nbr : nbrs) {
                min_time = min(min_time, last_seen[nbr]);
            }
            int count = 0;
            next = nbrs[0];
            for (int nbr : nbrs) {
                if (last_seen[nbr] != min_time) continue;
                next = reservoir_pick(nbr, count, next, rng);
            }
        }
        age++;
        last_seen[next] = age;
        position = next;
        history.push_back(next);
        if (++hops > max_steps) throw_step_limit(max_steps);
    }
}

inline void sample_nc(
    vector<int> &history,
    const vector<vector<int>> &adj,
    int src_idx,
    int tgt_idx,
    int disabled,
    vector<int> &last_seen,
    mt19937 &rng,
    int max_steps
) {
    fill(last_seen.begin(), last_seen.end(), -1);
    int age = 0;
    last_seen[src_idx] = age;
    int position = src_idx;
    int hops = 0;
    while (position != tgt_idx) {
        const vector<int> &nbrs = adj[static_cast<size_t>(position)];
        int enabled = 0;
        for (int nbr : nbrs) {
            if (nbr != disabled) enabled++;
        }
        if (enabled == 0) {
            throw runtime_error("NC walk reached a node whose only neighbors are disabled");
        }
#if RW_DIRECT_TO_VISIBLE_TARGET
        if (disabled != tgt_idx) {
            int next;
            if (pick_visible_target(nbrs, tgt_idx, next)) {
                history.push_back(next);
                return;
            }
        }
#endif
        int next = nbrs[0];
        if (enabled == 1) {
            for (int nbr : nbrs) {
                if (nbr != disabled) {
                    next = nbr;
                    break;
                }
            }
        } else {
            int min_time = numeric_limits<int>::max();
            for (int nbr : nbrs) {
                if (nbr == disabled) continue;
                min_time = min(min_time, last_seen[nbr]);
            }
            int count = 0;
            next = src_idx;
            for (int nbr : nbrs) {
                if (nbr == disabled || last_seen[nbr] != min_time) continue;
                next = reservoir_pick(nbr, count, next, rng);
            }
        }
        age++;
        last_seen[next] = age;
        position = next;
        history.push_back(next);
        if (++hops > max_steps) throw_step_limit(max_steps);
    }
}

inline void sample_hs(
    vector<int> &history,
    const vector<vector<int>> &adj,
    int src_idx,
    int tgt_idx,
    int seed,
    int node_count,
    vector<uint64_t> &visited_bits,
    vector<uint64_t> &hs_scores,
    mt19937 &rng,
    int max_steps
) {
    for (int u = 0; u < node_count; u++) {
        hs_scores[static_cast<size_t>(u)] = hs_deterministic_node_score(u, seed);
    }
    fill(visited_bits.begin(), visited_bits.begin() + ((static_cast<size_t>(node_count) + 63) / 64), 0);
    visited_bit_set(visited_bits, src_idx);

    int position = src_idx;
    int previous = -1;
    int hops = 0;
    while (position != tgt_idx) {
        const vector<int> &nbrs = adj[static_cast<size_t>(position)];
        int next;
#if RW_DIRECT_TO_VISIBLE_TARGET
        if (pick_visible_target(nbrs, tgt_idx, next)) {
            history.push_back(next);
            return;
        }
#endif
        if (nbrs.size() == 1) {
            next = nbrs[0];
        } else {
            bool any_unvisited = false;
            for (int nbr : nbrs) {
                if (!visited_bit_test(visited_bits, nbr)) {
                    any_unvisited = true;
                    break;
                }
            }

            if (any_unvisited) {
                uint64_t max_score = 0;
                int count = 0;
                next = nbrs[0];
                for (int nbr : nbrs) {
                    if (visited_bit_test(visited_bits, nbr)) continue;
                    const uint64_t score = hs_scores[static_cast<size_t>(nbr)];
                    if (score > max_score) {
                        max_score = score;
                        count = 1;
                        next = nbr;
                    } else if (score == max_score) {
                        next = reservoir_pick(nbr, count, next, rng);
                    }
                }
            } else {
                int count = 0;
                next = nbrs[0];
                for (int nbr : nbrs) {
                    if (nbr == previous) continue;
                    next = reservoir_pick(nbr, count, next, rng);
                }
                if (count == 0) {
                    next = nbrs[static_cast<size_t>(rng()) % nbrs.size()];
                }
            }
        }
        visited_bit_set(visited_bits, next);
        previous = position;
        position = next;
        history.push_back(next);
        if (++hops > max_steps) throw_step_limit(max_steps);
    }
}

}  // namespace walk_sample_detail

// Fast path: parse variant once, reuse scratch buffers across runs.
inline void sample_random_walk_history(
    WalkSampleScratch &scratch,
    const vector<vector<int>> &adj,
    RwVariant variant,
    int src_idx,
    int tgt_idx,
    int seed,
    int node_count,
    int max_steps = 100000
) {
    using namespace walk_sample_detail;
    scratch.history.clear();
    scratch.history.push_back(src_idx);
    mt19937 rng(static_cast<uint32_t>(seed));

    switch (variant) {
    case RwVariant::R:
        sample_r(scratch.history, adj, src_idx, tgt_idx, rng, max_steps);
        break;
    case RwVariant::NB:
        sample_nb(scratch.history, adj, src_idx, tgt_idx, rng, max_steps);
        break;
    case RwVariant::LRV:
        sample_lrv(scratch.history, adj, src_idx, tgt_idx, scratch.last_seen, rng, max_steps);
        break;
    case RwVariant::NC: {
        const int disabled = nc_disabled_node(src_idx, tgt_idx, seed, node_count);
        sample_nc(scratch.history, adj, src_idx, tgt_idx, disabled, scratch.last_seen, rng, max_steps);
        break;
    }
    case RwVariant::HS:
        sample_hs(
            scratch.history,
            adj,
            src_idx,
            tgt_idx,
            seed,
            node_count,
            scratch.visited_bits,
            scratch.hs_scores,
            rng,
            max_steps
        );
        break;
    default:
        throw runtime_error("Unknown random walk variant");
    }
}

inline vector<int> sample_random_walk_history(
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
    sample_random_walk_history(scratch, adj, variant, src_idx, tgt_idx, seed, node_count, max_steps);
    return std::move(scratch.history);
}
