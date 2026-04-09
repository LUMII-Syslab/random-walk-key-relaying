#pragma once

#include <algorithm>
#include <iomanip>
#include <random>
#include <sstream>
#include <string>
#include <vector>

using namespace std;

inline string fmt_2dp(double t)
{
    // "at most two digits after decimal": print 2dp then trim trailing
    // zeros/dot.
    ostringstream oss;
    oss.setf(ios::fixed);
    oss << setprecision(2) << t;
    string s = oss.str();
    // trim trailing zeros
    while (!s.empty() && s.back() == '0')
        s.pop_back();
    if (!s.empty() && s.back() == '.')
        s.pop_back();
    return s;
};

inline string fmt_3dp(double t)
{
    ostringstream oss;
    oss.setf(ios::fixed);
    oss << setprecision(3) << t;
    string s = oss.str();
    return s;
}

inline int choose_uniformly(const vector<int> &choices, mt19937 &rng){
    int idx = rng() % choices.size();
    return choices[idx];
}
