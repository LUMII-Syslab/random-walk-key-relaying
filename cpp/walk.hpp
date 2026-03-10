#pragma once
#include <array>
#include <cstdint>
#include <map>
#include <random>
#include <vector>
#include "utils.hpp"
#include <set>
#include <cassert>
using namespace std;

#ifndef HS_ENABLE_LRV_FALLBACK
#define HS_ENABLE_LRV_FALLBACK 1
#endif

struct RwToken{
    virtual int choose_next_and_update(int v, const vector<int> &nbrs) = 0;
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
    int choose_next_and_update(int __attribute__((unused)) v, const vector<int> &nbrs){
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
    int choose_next_and_update(int __attribute__((unused)) v, const vector<int> &nbrs){
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
    int choose_next_and_update(int __attribute__((unused)) v, const vector<int> &nbrs){
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
// 
// if all neighbors have been visited, we prefer the least recently visited neighbor
class HsToken: public RwToken{
    int src_node_idx;
    int tgt_node_idx;
    set<int> visited;
    map<int,int> last_visited;
    int age;
    mt19937 rng;
    int walk_seed;
    void append_to_history(int node_idx){
        age++;
        last_visited[node_idx] = age;
    }
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
        age = 0;
        visited.insert(src_node_idx);
        last_visited[src_node_idx] = age;
    }
    int choose_next_and_update(int __attribute__((unused)) v, const vector<int> &nbrs){
        if(nbrs.size()==1) {
            int chosen = nbrs[0];
            visited.insert(chosen);
            append_to_history(chosen);
            return chosen;
        }

        vector<int> candidate_nbrs;
        for(int nbr: nbrs){
            if(visited.count(nbr) == 0) candidate_nbrs.push_back(nbr);
        }
        if(candidate_nbrs.empty()) {
#if HS_ENABLE_LRV_FALLBACK
            int min_time = numeric_limits<int>::max();
            for(int nbr: nbrs){
                min_time = min(min_time, last_visited[nbr]);
            }
            for(int nbr: nbrs){
                if(last_visited[nbr] == min_time) candidate_nbrs.push_back(nbr);
            }
#else
            candidate_nbrs = nbrs;
#endif
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
        return chosen;
    }

};

// bivalent-vertex-optimized HS walk (BHS)
class BhsToken: public RwToken{
    int src, tgt, seed;
    mt19937 rng;

    int age; // hop count since start
    map<int,int> last_vis;
    map<int,uint64_t> override_score;
    uint64_t psi = 0; // highest unvisited neighbor score in last intersection

    uint64_t _get_score(int v, int seed) const {
        seed_seq seq{v, seed};
        array<uint32_t, 2> words{};
        seq.generate(words.begin(), words.end());
        return (static_cast<uint64_t>(words[0]) << 32) | words[1];
    }
    uint64_t get_score(int u) const {
        if(override_score.count(u) > 0) return override_score.at(u);
        return _get_score(u, seed);
    }
    int get_last_vis_time(int v) const{
        return last_vis.count(v) == 0 ? -1 : last_vis.at(v);
    }
    int pick_lrv(const vector<int> &nbrs, mt19937 &rng) const{
        int min_time = numeric_limits<int>::max();
        vector<int> choices;
        for(int nbr: nbrs){
            int nbr_time = get_last_vis_time(nbr);
            if(nbr_time == min_time) choices.push_back(nbr);
            else if(nbr_time < min_time) {
                min_time = nbr_time;
                choices.clear();
                choices.push_back(nbr);
            }
        }
        return choose_uniformly(choices, rng);
    }
    int pick_max_score(const vector<int> &choices, mt19937 &rng) const{
        assert(choices.size()>0);
        uint64_t max_score = 0;
        vector<int> filtered_choices;
        for (int c : choices) {
            uint64_t score = get_score(c);
            if (score == max_score) filtered_choices.push_back(c);
            if (score > max_score) {
                max_score = score;
                filtered_choices.clear();
                filtered_choices.push_back(c);
            }
        }
        assert(filtered_choices.size()>0);
        return choose_uniformly(filtered_choices, rng);
    }
    vector<int> filter_unvisited(const vector<int> &nbrs) const{
        vector<int> unvisited_nbrs;
        for(int nbr: nbrs){
            if(last_vis.count(nbr) == 0) unvisited_nbrs.push_back(nbr);
        }
        return unvisited_nbrs;
    }

    bool visited(int u) const{
        return last_vis.count(u) > 0;
    }

    int process_bivalent(int v, const vector<int> &nbrs, mt19937 &rng) {
        assert(nbrs.size()==2);

        if(filter_unvisited(nbrs).size()==2){
            return pick_max_score(filter_unvisited(nbrs),rng);
        }
        if(filter_unvisited(nbrs).size()==0){
            return pick_lrv(nbrs, rng);
        }

        int u = nbrs[0], p = nbrs[1];
        if(visited(u)) swap(u, p);
        // u is the unvisited neighbor
        // p is the previous vertex

        if(get_score(u) < psi) {
            // we must start the backtracking process
            override_score[v] = get_score(u);
            last_vis.erase(v);
            return p;
        }
        
        return u;
    }
    
    int process_intersection(int v, const vector<int> &nbrs, mt19937 &rng) {
        assert(nbrs.size()>2);

        vector<int> unvisited_nbrs = filter_unvisited(nbrs);
        if(unvisited_nbrs.size()==0) {
            psi = 0;
            return pick_lrv(nbrs, rng);
        }

        int u = pick_max_score(unvisited_nbrs, rng);
        psi = 0;
        for(int nbr: unvisited_nbrs){
            if(nbr == u) continue;
            psi = max(psi, get_score(nbr)); // update psi
        }
        return u;
    }
public:
    BhsToken(int src, int tgt, int seed){
        this->src = src;
        this->tgt = tgt;
        this->seed = seed;
        this->rng = mt19937(seed);
        this->age = 0;
        this->last_vis[this->src] = this->age;
    }
    int choose_next_and_update(int v, const vector<int> &nbrs){
        int chosen;
        if(nbrs.size()==1) chosen = nbrs[0];
        else if(nbrs.size()==2) chosen = process_bivalent(v, nbrs, rng);
        else chosen = process_intersection(v, nbrs, rng);

        age++;
        last_vis[chosen] = age;
        return chosen;
    }
};