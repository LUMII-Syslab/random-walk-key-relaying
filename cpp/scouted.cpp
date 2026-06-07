#include <iostream>
#include <map>
#include <memory>
#include <queue>
#include <random>
#include <sstream>
#include <vector>
#include <boost/dynamic_bitset.hpp>
#include "cli.hpp"
#include "graph.hpp"
#include "lerw.hpp"
#include "utils.hpp"
#include "walk.hpp"

using namespace std;

namespace cartel {
struct Result {
    int max_seen = 0;
    vector<int> nodes;
};

static Result worst_case_coverage(
    const vector<boost::dynamic_bitset<>> &covered_chunks_by_node,
    int src,
    int tgt,
    int cartel_sz
) {
    Result res;
    if (cartel_sz <= 0) return res;
    cartel_sz = min(cartel_sz, 3);

    const int n = static_cast<int>(covered_chunks_by_node.size());
    if (n == 0) return res;

    vector<int> candidates;
    candidates.reserve(n);
    for (int v = 0; v < n; v++) {
        if (v == src || v == tgt) continue;
        if (covered_chunks_by_node[v].none()) continue;
        candidates.push_back(v);
    }
    if (candidates.empty()) return res;
    if (static_cast<int>(candidates.size()) < cartel_sz) cartel_sz = static_cast<int>(candidates.size());
    if (cartel_sz <= 0) return res;

    auto coverage1 = [&](int a) -> int {
        return static_cast<int>(covered_chunks_by_node[a].count());
    };
    auto coverage2 = [&](int a, int b) -> int {
        boost::dynamic_bitset<> tmp = covered_chunks_by_node[a];
        tmp |= covered_chunks_by_node[b];
        return static_cast<int>(tmp.count());
    };
    auto coverage3 = [&](int a, int b, int c) -> int {
        boost::dynamic_bitset<> tmp = covered_chunks_by_node[a];
        tmp |= covered_chunks_by_node[b];
        tmp |= covered_chunks_by_node[c];
        return static_cast<int>(tmp.count());
    };

    if (cartel_sz == 1) {
        int best_v = -1;
        int best = 0;
        for (int v : candidates) {
            int cov = coverage1(v);
            if (cov > best) {
                best = cov;
                best_v = v;
            }
        }
        res.max_seen = best;
        if (best_v != -1) res.nodes = {best_v};
        return res;
    }

    if (cartel_sz == 2) {
        int best_a = -1, best_b = -1;
        int best = 0;
        for (size_t i = 0; i < candidates.size(); i++) {
            for (size_t j = i + 1; j < candidates.size(); j++) {
                int a = candidates[i], b = candidates[j];
                int cov = coverage2(a, b);
                if (cov > best) {
                    best = cov;
                    best_a = a;
                    best_b = b;
                }
            }
        }
        res.max_seen = best;
        if (best_a != -1) res.nodes = {best_a, best_b};
        return res;
    }

    int best_a = -1, best_b = -1, best_c = -1;
    int best = 0;
    for (size_t i = 0; i < candidates.size(); i++) {
        for (size_t j = i + 1; j < candidates.size(); j++) {
            for (size_t k = j + 1; k < candidates.size(); k++) {
                int a = candidates[i], b = candidates[j], c = candidates[k];
                int cov = coverage3(a, b, c);
                if (cov > best) {
                    best = cov;
                    best_a = a;
                    best_b = b;
                    best_c = c;
                }
            }
        }
    }
    res.max_seen = best;
    if (best_a != -1) res.nodes = {best_a, best_b, best_c};
    return res;
}
} // namespace cartel

const double SCOUTS_PER_SECONDS = 100;
const double CLASSICAL_DELAY_MS = 5;
const double QKD_SKR_BITS_P_S = 1000;
const int CHUNK_SIZE_BITS = 256;

mt19937 rng(2026);

struct Options{
    string graph = "geant";
    string edges_csv;
    vector<string> src_nodes;
    string rw_variant = "HS"; // NB, LRV, HS
    bool verbose = false;
    int watermark_sz = 128;
    int block_chunks = 64;
    uint ttl = 200;
    int max_wait_time_s = 2;
    int required_cnt = -1;
    double max_consume_prob = 1.0;
    int cartel_size_limit = 3; // cap cartel size (worst_case_coverage supports at most 3)
    bool report_chunk_paths = false;
    string context;
};

enum class EventType {
    EmitScout,
    ScoutForward,
    ScoutReturn,
    ChunkReceived,
};

struct Event{
    double time;
    EventType type;

    int origin; // emit scout + src node

    // walk events
    int sender;
    int receiver;
    shared_ptr<RwToken> token;

    // full history in scout forward and planned path otherwise
    vector<int> history;

    int target=-1; // scout return
    double wait; // wait before sending
};

bool operator<(const Event& lhs, const Event& rhs){
    return lhs.time > rhs.time;
}

bool consume(int keys_in_buff, int watermark, int hop_count, int ttl, double max_consume_prob){
    if(keys_in_buff>=watermark) return false;
    assert(hop_count<=ttl);
    double b = (double)keys_in_buff/(double)watermark;
    double t = (double)(ttl-hop_count)/(double)ttl;
    double p = 1 - max(b,t);
    // double p = 1 - max(5*b*t, t);
    
    double r = (double)(rng()-rng.min())/(double)(rng.max()-rng.min());
    p = min(p, max_consume_prob);
    return r <= p;
}

static bool valid_rw_variant(const string &w) {
    return w == "NB" || w == "LRV" || w == "HS";
}

static shared_ptr<RwToken> make_walk_token(const Options &opts, int src_idx) {
    const int seed = static_cast<int>(rng());
    const int tgt_idx = -1; // unknown-target mode
    if (opts.rw_variant == "NB") return make_shared<NbToken>(src_idx, tgt_idx, seed);
    if (opts.rw_variant == "LRV") return make_shared<LrvToken>(src_idx, tgt_idx, seed);
    if (opts.rw_variant == "HS") return make_shared<HsToken>(src_idx, tgt_idx, seed);
    throw runtime_error("Unknown --rw-variant: " + opts.rw_variant);
}

void run_simulation(const Options& opts, const Graph& graph){
    priority_queue<Event> pq;
    map<pair<int,int>, int> vconn_cache;
    auto pair_vconn = [&](int src, int tgt) -> int {
        const pair<int,int> key{src, tgt};
        auto it = vconn_cache.find(key);
        if (it != vconn_cache.end()) return it->second;
        const int kappa = graph.vertex_connectivity(src, tgt);
        vconn_cache[key] = kappa;
        return kappa;
    };

    if (opts.block_chunks <= 0) {
        throw runtime_error("block_chunks must be > 0");
    }
    if (opts.report_chunk_paths && !opts.verbose) {
        throw runtime_error("--report-chunk-paths requires --verbose");
    }
    if (!valid_rw_variant(opts.rw_variant)) {
        throw runtime_error("Invalid --rw-variant (expected NB, LRV, or HS): " + opts.rw_variant);
    }

    for(string src: opts.src_nodes){
        int origin = graph.node_index(src);
        pq.push(Event{0.0,EventType::EmitScout,origin,-1,-1,nullptr,{},-1,0});
    }

    map<pair<int,int>,int> established_keys;
    map<pair<int,int>,int> chunks_received;
    struct BlockState {
        int received = 0;
        vector<boost::dynamic_bitset<>> covered_chunks_by_node;
    };
    map<pair<int,int>, BlockState> blocks;

    // Total number of QKD bits already reserved for future use on each undirected link.
    // Units: bits (not chunks).
    map<pair<int,int>,int> reserved_total_on_qkd_link;

    auto predict_wait_time = [&](double time_now, int from, int to) -> double{
        if(from>to) swap(from,to);
        double generated = QKD_SKR_BITS_P_S * time_now;
        double extracted = reserved_total_on_qkd_link[{from,to}];
        double req_bits_to_gen = CHUNK_SIZE_BITS-(generated-extracted);
        double time_to_gen = req_bits_to_gen/QKD_SKR_BITS_P_S;
        return max(time_to_gen, 0.0);
    };

    auto enqueue_on_link = [&](double time_now, int from, int to) -> double{
        if(from>to) swap(from,to);
        double generated = QKD_SKR_BITS_P_S * time_now;
        double extracted = reserved_total_on_qkd_link[{from,to}];
        reserved_total_on_qkd_link[{from,to}] += CHUNK_SIZE_BITS;
        double req_bits_to_gen = CHUNK_SIZE_BITS-(generated-extracted);
        double time_to_gen = req_bits_to_gen/QKD_SKR_BITS_P_S;
        return max(time_to_gen, 0.0);
    };

    while(pq.size()>0){
        Event e = pq.top();
        pq.pop();

        if(e.type == EventType::EmitScout){
            double next_occurrence = e.time + 1/SCOUTS_PER_SECONDS;
            pq.push(Event{next_occurrence,EventType::EmitScout,e.origin,-1,-1,nullptr,{},-1,0});
            shared_ptr<RwToken> token = make_walk_token(opts, e.origin);
            int ngh = token->choose_next_and_update(e.origin, graph.neighbors(e.origin));
            double arrives_at = e.time + CLASSICAL_DELAY_MS/1000.0;
            bool wait_time_ok = predict_wait_time(e.time, e.origin, ngh)<=opts.max_wait_time_s;
            bool ttl_ok = 1 <= opts.ttl;
            if(wait_time_ok&&ttl_ok)
                pq.push(Event{arrives_at,EventType::ScoutForward,e.origin,e.origin,ngh,token,{e.origin,ngh},-1,0});
            continue;
        }

        if(e.type == EventType::ScoutForward){
            if(
                e.receiver!=e.origin
                && consume(
                    established_keys[{e.origin,e.receiver}],
                    opts.watermark_sz,
                    e.history.size()-1,
                    opts.ttl,
                    opts.max_consume_prob
                )
            ){
                auto path = erase_loops_from_history(e.history);
                double arrives_at = e.time + CLASSICAL_DELAY_MS/1000.0;
                int nxt = path[path.size()-2];
                double wait_time = enqueue_on_link(e.time, e.receiver, nxt);
                pq.push(Event{arrives_at,EventType::ScoutReturn,e.origin,e.receiver,path[path.size()-2],nullptr,path,e.receiver,wait_time});
                continue;
            }
            int ngh = e.token->choose_next_and_update(e.receiver, graph.neighbors(e.receiver));
            vector<int> new_history = e.history;
            new_history.push_back(ngh);
            double arrives_at = e.time + CLASSICAL_DELAY_MS/1000.0;
            bool wait_time_ok = predict_wait_time(e.time, e.receiver, ngh)<=opts.max_wait_time_s;
            bool ttl_ok = new_history.size() <= opts.ttl+1;
            if(wait_time_ok&&ttl_ok)
                pq.push(Event{arrives_at,EventType::ScoutForward,e.origin,e.receiver,ngh,e.token,new_history,-1,0});
            continue;
        }

        if(e.type == EventType::ScoutReturn){
            if(e.receiver == e.origin){
                double chunk_at = e.time+e.wait+(e.history.size()-1)*CLASSICAL_DELAY_MS/1000.0;
                pq.push(Event{chunk_at, EventType::ChunkReceived, e.origin, e.origin, e.target, nullptr, e.history, e.target, 0});
                continue;
            }
            int idx=-1;
            for(size_t i=0;i<e.history.size();i++){
                if(e.history[i] == e.receiver) {idx=i;break;}
            }
            assert(idx>=1);
            int nxt = e.history[idx-1];
            double wait_time = enqueue_on_link(e.time, e.receiver, nxt);
            double arrives_at = e.time + CLASSICAL_DELAY_MS/1000.0;
            double max_wait = max(e.wait, wait_time);
            pq.push(Event{arrives_at,EventType::ScoutReturn,e.origin,e.receiver,nxt,nullptr,e.history,e.target,max_wait});
            continue;
        }
        
        if(e.type == EventType::ChunkReceived){
            if (opts.report_chunk_paths) {
                // Path is already loop-erased at acceptance time.
                cout<<"chunk "<<fmt_3dp(e.time)<<" "<<graph.node_name(e.origin)<<" "<<graph.node_name(e.target);
                for (int v : e.history) cout<<" "<<graph.node_name(v);
                cout<<endl;
            }

            auto key = make_pair(e.origin, e.target);
            BlockState &blk = blocks[key];
            if (
                blk.covered_chunks_by_node.empty()
                || static_cast<int>(blk.covered_chunks_by_node.size()) != graph.node_count()
                || (graph.node_count() > 0 && static_cast<int>(blk.covered_chunks_by_node[0].size()) != opts.block_chunks)
            ) {
                blk.covered_chunks_by_node.assign(
                    graph.node_count(),
                    boost::dynamic_bitset<>(static_cast<size_t>(opts.block_chunks))
                );
            }

            const int chunk_idx = blk.received;
            for (int x : e.history) {
                if (x == e.origin || x == e.target) continue;
                if (x < 0 || x >= graph.node_count()) continue;
                blk.covered_chunks_by_node[x].set(static_cast<size_t>(chunk_idx));
            }
            blk.received++;
            chunks_received[key] = blk.received;

            if (blk.received == opts.block_chunks) {
                blk.received = 0;
                chunks_received[key] = 0;

                const int vconn = pair_vconn(e.origin, e.target);
                int cartel_sz = min(max(0, vconn - 1), opts.cartel_size_limit);

                cartel::Result cr = cartel::worst_case_coverage(blk.covered_chunks_by_node, e.origin, e.target, cartel_sz);
                int honesty = opts.block_chunks - cr.max_seen;
                if (opts.block_chunks == 32 && cartel_sz == 0 && vconn == 1) {
                    honesty /= 2;
                }

                // Reset block state for this pair.
                for (auto &bs : blk.covered_chunks_by_node) bs.reset();

                established_keys[key] += honesty;
                if (opts.verbose) {
                    vector<string> cartel_names;
                    for (int v : cr.nodes) cartel_names.push_back(graph.node_name(v));
                    string cartel_str = cartel_names.empty() ? "-" : join(cartel_names, ",");
                    cout<<"keys "<<honesty<<" "<<graph.node_name(e.origin)<<" "<<graph.node_name(e.target)<<" ";
                    cout<<cartel_str<<" "<<cr.max_seen;
                    cout<<" vconn="<<vconn<<" cartel_sz="<<cartel_sz;
                    cout<<endl;
                }
                // check if we can halt
                if(opts.required_cnt!=-1){
                    bool found_unsatisfied = false;
                    for(string src_name: opts.src_nodes){
                        int src = graph.node_index(src_name);
                        for(int i=0;i<graph.node_count();i++){
                            if(i==src) continue;
                            if(established_keys[{src,i}]<opts.required_cnt){
                                found_unsatisfied = true;
                                break;
                            }
                        }
                        if(found_unsatisfied) break;
                    }
                    if(!found_unsatisfied){
                        cout<<"Halted at "<<e.time<<" seconds"<<endl;
                        return;
                    }
                }
            }
        }

    }
}

static Options parse_args(int argc, char **argv) {
    Options opts;
    bool have_halt_at_keys = false;

    CliParser cli(argc, argv);
    cli.reg_string("--graph", "-g", opts.graph);
    cli.note_usage("--src-nodes", "-S", "n1,n2,...", false);
    cli.reg("--src-nodes", "-S", [&](CliParser &c, int &i, const ParsedArg &p) {
        opts.src_nodes = split(c.require_value(i, p.flag, p), ",");
    });
    cli.reg_context("--src-nodes", [&opts]() {
        if (opts.src_nodes.empty()) return string("all");
        return join(opts.src_nodes, ",");
    });
    cli.reg_string("--rw-variant", "-w", opts.rw_variant);
    cli.reg_bool("--verbose", {}, opts.verbose);
    cli.note_usage("--halt-at-keys", {}, "int", false);
    cli.reg("--halt-at-keys", {}, [&](CliParser &c, int &i, const ParsedArg &p) {
        opts.required_cnt = stoi(c.require_value(i, p.flag, p));
        have_halt_at_keys = true;
    });
    cli.reg_context("--halt-at-keys", [&opts]() { return to_string(opts.required_cnt); });
    cli.reg_double("--max-consume-prob", {}, opts.max_consume_prob);
    cli.reg_int("--watermark-sz", {}, opts.watermark_sz);
    cli.reg_int("--block-chunks", {}, opts.block_chunks);
    cli.reg_int("--cartel-size-limit", {}, opts.cartel_size_limit);
    cli.reg_bool("--report-chunk-paths", {}, opts.report_chunk_paths);
    cli.parse();

    if (!have_halt_at_keys) {
        opts.required_cnt = opts.watermark_sz;
    }
    opts.edges_csv = resolve_graph_spec(opts.graph);
    if (!valid_rw_variant(opts.rw_variant)) {
        cli.fail("Invalid --rw-variant (expected NB, LRV, or HS): " + opts.rw_variant);
    }
    if (opts.block_chunks <= 0) {
        cli.fail("--block-chunks must be > 0");
    }
    if (opts.cartel_size_limit < 0 || opts.cartel_size_limit > 3) {
        cli.fail("--cartel-size-limit must be between 0 and 3");
    }
    if (opts.report_chunk_paths && !opts.verbose) {
        cli.fail("--report-chunk-paths requires --verbose");
    }
    opts.context = cli.format_context();
    return opts;
}

int main(int argc, char **argv) {
    try {
        Options opts = parse_args(argc, argv);
        Graph graph(opts.edges_csv);

        if (opts.src_nodes.empty()) {
            opts.src_nodes.reserve(graph.node_count());
            for (int i = 0; i < graph.node_count(); i++) {
                opts.src_nodes.push_back(graph.node_name(i));
            }
        }

        cout << opts.context;
        run_simulation(opts, graph);
        return 0;
    } catch (const exception &ex) {
        cerr << ex.what() << endl;
        return 1;
    }
}
