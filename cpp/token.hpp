#pragma once

#include <vector>
using namespace std;

struct RwToken{
    virtual int choose_next_and_update(const vector<int> &nbrs) = 0;
};