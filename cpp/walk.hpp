#pragma once
#include <array>
#include <cstdint>
#include <map>
#include <random>
#include <vector>
#include "utils.hpp"
#include <set>
using namespace std;

struct RwToken{
    virtual int choose_next_and_update(const vector<int> &nbrs) = 0;
};

// simple random walk (R)
class RToken: public RwToken{
    int src_node_idx;
    int tgt_node_idx;
    mt19937 rng;
public:
    RToken(int src, int tgt, int seed): rng(seed){
        src_node_idx = src;
        tgt_node_idx = tgt;
    }
    int choose_next_and_update(const vector<int> &nbrs){
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
        src_node_idx = src;
        tgt_node_idx = tgt;
        current = src_node_idx;
        previous = -1;
    }
    int choose_next_and_update(const vector<int> &nbrs){
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
            if(last_seen.count(nbr) == 0) nbr_time[nbr] = 0;
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
    int choose_next_and_update(const vector<int> &nbrs){
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

// highest-score vertex (HS) random walk variant
// vertex scores are predetermined at the start of the walk
// the intuitive idea is that in one of the many walks
// the "evil" vertex will be assigned a low value and therefore not visited
class HsToken: public RwToken{
    int src_node_idx;
    int tgt_node_idx;
    set<int> visited;
    mt19937 rng;
    int walk_seed;
    uint64_t get_node_score(int node_idx) const {
        if(visited.count(node_idx) > 0) return 0;
        // Deterministic per-walk/per-node score without hard-coded constants.
        seed_seq seq{node_idx, walk_seed};
        array<uint32_t, 2> words{};
        seq.generate(words.begin(), words.end());
        return (static_cast<uint64_t>(words[0]) << 32) | words[1];
    }
public:
    HsToken(int src, int tgt, int seed): rng(seed){
        src_node_idx = src;
        tgt_node_idx = tgt;
        walk_seed = seed;
        visited.insert(src_node_idx);
    }
    int choose_next_and_update(const vector<int> &nbrs){
        if(nbrs.size()==1) {
            int chosen = nbrs[0];
            visited.insert(chosen);
            return chosen;
        }

        vector<int> candidate_nbrs;
        for(int nbr: nbrs){
            if(visited.count(nbr) == 0) candidate_nbrs.push_back(nbr);
        }
        if(candidate_nbrs.empty()) candidate_nbrs = nbrs;

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
        return chosen;
    }

};