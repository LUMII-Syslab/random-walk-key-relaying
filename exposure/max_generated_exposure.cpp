#include <algorithm>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

using namespace std;

struct Graph {
    vector<string> names;
    vector<vector<int>> adj;
};

static string trim(const string &s) {
    size_t i = 0;
    while (i < s.size() && isspace(static_cast<unsigned char>(s[i]))) i++;
    size_t j = s.size();
    while (j > i && isspace(static_cast<unsigned char>(s[j - 1]))) j--;
    return s.substr(i, j - i);
}

static vector<string> split_csv_line(const string &line) {
    vector<string> out;
    string cur;
    bool in_quotes = false;
    for (size_t i = 0; i < line.size(); i++) {
        const char c = line[i];
        if (c == '"') {
            if (in_quotes && i + 1 < line.size() && line[i + 1] == '"') {
                cur.push_back('"');
                i++;
            } else {
                in_quotes = !in_quotes;
            }
        } else if (c == ',' && !in_quotes) {
            out.push_back(trim(cur));
            cur.clear();
        } else {
            cur.push_back(c);
        }
    }
    out.push_back(trim(cur));
    return out;
}

static Graph load_edges_csv(const string &path) {
    ifstream in(path);
    if (!in) throw runtime_error("Failed to open edges file: " + path);

    string header_line;
    if (!getline(in, header_line)) throw runtime_error("Edges CSV is empty");
    auto header = split_csv_line(header_line);

    int c_src = -1;
    int c_tgt = -1;
    for (int i = 0; i < static_cast<int>(header.size()); i++) {
        string h = header[i];
        transform(h.begin(), h.end(), h.begin(), [](unsigned char c) { return static_cast<char>(tolower(c)); });
        if (h == "source") c_src = i;
        if (h == "target") c_tgt = i;
    }
    if (c_src < 0 || c_tgt < 0) throw runtime_error("CSV must contain Source,Target columns");

    unordered_map<string, int> idx;
    vector<string> names;
    vector<pair<int, int>> edges;

    auto get_or_add = [&](const string &node_name) -> int {
        auto it = idx.find(node_name);
        if (it != idx.end()) return it->second;
        const int id = static_cast<int>(names.size());
        idx.emplace(node_name, id);
        names.push_back(node_name);
        return id;
    };

    string line;
    while (getline(in, line)) {
        if (trim(line).empty()) continue;
        auto cols = split_csv_line(line);
        if (c_src >= static_cast<int>(cols.size()) || c_tgt >= static_cast<int>(cols.size())) continue;
        const string s = cols[c_src];
        const string t = cols[c_tgt];
        if (s.empty() || t.empty() || s == t) continue;
        const int u = get_or_add(s);
        const int v = get_or_add(t);
        edges.emplace_back(u, v);
    }

    if (names.empty()) throw runtime_error("No nodes parsed from edge list");

    vector<vector<int>> adj(names.size());
    for (auto [u, v] : edges) {
        adj[u].push_back(v);
        adj[v].push_back(u);
    }
    for (auto &nbrs : adj) sort(nbrs.begin(), nbrs.end());

    return Graph{std::move(names), std::move(adj)};
}

static int choose_lrv_next(const vector<int> &nbrs, const vector<int> &history, mt19937 &rng) {
    if (nbrs.empty()) throw runtime_error("Node has no neighbors");
    if (nbrs.size() == 1) return nbrs[0];

    unordered_map<int, int> last_seen;
    last_seen.reserve(history.size());
    for (int i = 0; i < static_cast<int>(history.size()); i++) last_seen[history[i]] = i;

    int best_last = numeric_limits<int>::max();
    vector<int> choices;
    for (int n : nbrs) {
        const auto it = last_seen.find(n);
        const int last = (it == last_seen.end()) ? -1 : it->second;
        if (last < best_last) {
            best_last = last;
            choices.clear();
        }
        if (last == best_last) choices.push_back(n);
    }

    uniform_int_distribution<int> dist(0, static_cast<int>(choices.size()) - 1);
    return choices[dist(rng)];
}

static vector<int> run_lrv_walk(const Graph &g, int src, int dst, mt19937 &rng, int max_steps = 1000000) {
    vector<int> history;
    history.push_back(src);
    int cur = src;
    for (int step = 0; step < max_steps; step++) {
        if (cur == dst) return history;
        const int nxt = choose_lrv_next(g.adj[cur], history, rng);
        history.push_back(nxt);
        cur = nxt;
    }
    throw runtime_error("Walk exceeded max_steps before reaching destination");
}

struct PairExposure {
    double max_prob = 0.0;
    int node = -1;
};

static PairExposure estimate_pair_exposure(const Graph &g, int src, int dst, int walks, mt19937 &rng) {
    vector<int> seen_count(g.adj.size(), 0);
    vector<char> seen(g.adj.size(), 0);

    for (int k = 0; k < walks; k++) {
        auto history = run_lrv_walk(g, src, dst, rng);
        fill(seen.begin(), seen.end(), 0);
        for (int node : history) {
            if (node == src || node == dst) continue;
            if (!seen[node]) {
                seen[node] = 1;
                seen_count[node]++;
            }
        }
    }

    PairExposure out;
    for (int node = 0; node < static_cast<int>(g.adj.size()); node++) {
        if (node == src || node == dst) continue;
        const double p = static_cast<double>(seen_count[node]) / static_cast<double>(walks);
        if (p > out.max_prob || (p == out.max_prob && out.node != -1 && g.names[node] < g.names[out.node])) {
            out.max_prob = p;
            out.node = node;
        }
    }
    return out;
}

int main(int argc, char **argv) {
    try {
        const string edges_path = (argc >= 2) ? argv[1] : "graphs/generated/edges.csv";
        constexpr int kExpectedNodes = 99;
        const int walks_per_pair = (argc >= 3) ? stoi(argv[2]) : 1000;
        constexpr double kEps = 1e-12;
        if (walks_per_pair <= 0) throw runtime_error("walks_per_pair must be positive");

        Graph g = load_edges_csv(edges_path);
        if (static_cast<int>(g.names.size()) != kExpectedNodes) {
            cerr << "Warning: graph has " << g.names.size() << " nodes (expected " << kExpectedNodes << ").\n";
        }

        mt19937 rng(2026);

        double best_prob = -1.0;
        int best_src = -1;
        int best_dst = -1;
        int best_node = -1;
        int filtered_prob_one = 0;
        const int total_pairs = static_cast<int>(g.adj.size() * (g.adj.size() - 1) / 2);
        int done_pairs = 0;

        for (int src = 0; src < static_cast<int>(g.adj.size()); src++) {
            for (int dst = src + 1; dst < static_cast<int>(g.adj.size()); dst++) {
                PairExposure pe = estimate_pair_exposure(g, src, dst, walks_per_pair, rng);
                if (fabs(pe.max_prob - 1.0) <= kEps) {
                    filtered_prob_one++;
                    done_pairs++;
                    if (done_pairs % 50 == 0 || done_pairs == total_pairs) {
                        cerr << "Processed " << done_pairs << "/" << total_pairs << "\r";
                        cerr.flush();
                    }
                    continue;
                }
                if (pe.max_prob > best_prob) {
                    best_prob = pe.max_prob;
                    best_src = src;
                    best_dst = dst;
                    best_node = pe.node;
                }
                done_pairs++;
                if (done_pairs % 50 == 0 || done_pairs == total_pairs) {
                    cerr << "Processed " << done_pairs << "/" << total_pairs << "\r";
                    cerr.flush();
                }
            }
        }
        cerr << "\n";

        if (best_src < 0 || best_dst < 0 || best_node < 0) {
            cout << "No valid pair found after filtering prob==1.\n";
            return 0;
        }

        cout << "source,target,lrv_max_vis_prob,lrv_max_vis_node\n";
        cout << g.names[best_src] << "," << g.names[best_dst] << "," << best_prob << "," << g.names[best_node] << "\n";
        cout << "filtered_pairs_prob_eq_1=" << filtered_prob_one << "\n";
        return 0;
    } catch (const exception &e) {
        cerr << "Fatal error: " << e.what() << "\n";
        return 1;
    }
}
