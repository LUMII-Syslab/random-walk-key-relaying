#pragma once
#include <vector>
#include <map>
#include <random>
#include "token.hpp"
using namespace std;


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
    int choose_uniformly(vector<int> choices){
        uniform_int_distribution<int> dist(0, choices.size()-1);
        return choices[dist(rng)];
    }
public:
    LrvToken(int src, int tgt, int seed): rng(seed){
        src_node_idx = src;
        tgt_node_idx = tgt;
        age = 0;
        last_seen[src_node_idx]=0;
    }
    int choose_next_and_update(const vector<int> &nbrs){
        if(nbrs.size()==1) return nbrs[0];

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
        int chosen = choose_uniformly(choices);

        append_to_history(chosen);
        return chosen;
    }
};