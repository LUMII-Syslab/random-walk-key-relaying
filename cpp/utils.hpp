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

inline std::vector<std::string> split(const std::string& s, string delimiter)
{
    std::vector<std::string> result;

    std::size_t current = 0;
    std::size_t p = s.find_first_of(delimiter, 0);

    while (p != std::string::npos)
    {
        result.emplace_back(s, current, p - current);
        current = p + 1;
        p = s.find_first_of(delimiter, current);
    }

    result.emplace_back(s, current);

    return result;
}

inline string join(vector<string> words, string delimiter){
    string res="";
    for(unsigned int i=0;i<words.size();i++){
        if(i>0)res+=delimiter;
        res+=words[i];
    }
    return res;
}
