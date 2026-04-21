#include <iostream>
#include <map>
#include <memory>
#include <queue>
#include <random>
#include <vector>
#include "graph.hpp"
#include "pair_vconn.hpp"
#include "utils.hpp"
#include "walk.hpp"
#include "cartel.hpp"

using namespace std;

const double SCOUTS_PER_SECONDS = 4;
const double CLASSICAL_DELAY_MS = 5;
const double QKD_SKR_BITS_P_S = 1000;
const int CHUNK_SIZE_BITS = 256;

mt19937 rng(2026);

struct Options{
    string edges_csv = "";
    string v_conn_csv = "";
    vector<string> src_nodes;
    bool verbose = false;
    int watermark_sz = 128;
    int block_chunks = 32;
    uint ttl = 200;
    int max_wait_time_s = 2;
    int required_cnt = -1;
    double max_consume_prob = 0.5;
    bool v_conn_cartel_size = false;

    void print(){
        cout<<"edges_csv: "<<edges_csv<<endl;
        cout<<"v_conn_csv: "<<v_conn_csv<<endl;
        cout<<"src_nodes: "<<join(src_nodes, ",")<<endl;
        cout<<"block_chunks: "<<block_chunks<<endl;
        cout<<"watermark_sz: "<<watermark_sz<<endl;
        cout<<"v_conn_cartel_size: "<<(v_conn_cartel_size?"true":"false")<<endl;
    }
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
    
    double r = (double)(rng()-rng.min())/(double)(rng.max()-rng.min());
    // p = min(p, max_consume_prob);
    return r <= p;
}

vector<int> erase_loops(vector<int> history){
    vector<int> res;
    map<int,size_t> lst_occ;
    for(size_t i=0;i<history.size();i++)
        lst_occ[history[i]]=i;
    for(size_t i=0;i<history.size();i++){
        int x = history[i];
        while(i!=lst_occ[x]) i++;
        res.push_back(x);
    }
    return res;
}

void run_simulation(const Options& opts, const Graph& graph, const map<pair<int,int>, int>* pair_vconn){
    priority_queue<Event> pq;

    if (opts.block_chunks <= 0) {
        throw runtime_error("block_chunks must be > 0");
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
        reserved_total_on_qkd_link[{from,to}]++;
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
            shared_ptr<RwToken> token = make_shared<HsToken>(e.origin, -1, rng());
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
                auto path = erase_loops(e.history);
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

                int cartel_sz = 1;
                int vconn = -1;
                if (opts.v_conn_cartel_size) {
                    if (pair_vconn == nullptr) {
                        throw runtime_error("--v-conn-cartel-size requires --v-conn-csv");
                    }
                    vconn = pair_vconn::lookup_or_throw(graph, *pair_vconn, e.origin, e.target);
                    cartel_sz = max(0, vconn - 1);
                    cartel_sz = min(cartel_sz, 3);
                }

                cartel::Result cr = cartel::worst_case_coverage(
                    blk.covered_chunks_by_node,
                    e.origin,
                    e.target,
                    cartel_sz
                );

                // Reset block state for this pair.
                for (auto &bs : blk.covered_chunks_by_node) bs.reset();

                int honesty = opts.block_chunks - cr.max_seen;
                established_keys[key] += honesty;
                if (opts.verbose) {
                    vector<string> cartel_names;
                    for (int v : cr.nodes) cartel_names.push_back(graph.node_name(v));
                    string cartel_str = cartel_names.empty() ? "-" : join(cartel_names, ",");
                    cout<<"keys "<<honesty<<" "<<graph.node_name(e.origin)<<" "<<graph.node_name(e.target)<<" ";
                    cout<<cartel_str<<" "<<cr.max_seen;
                    if (opts.v_conn_cartel_size) cout<<" vconn="<<vconn<<" cartel_sz="<<cartel_sz;
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

Options parse_args(int argc, char* argv[]);

int main(int argc, char* argv[]) {
    Options opts = parse_args(argc, argv);
    Graph graph = Graph(opts.edges_csv);

    opts.print();

    unique_ptr<map<pair<int,int>, int>> pair_vconn;
    if (opts.v_conn_cartel_size) {
        if (opts.v_conn_csv.empty()) {
            throw runtime_error("--v-conn-cartel-size requires --v-conn-csv <file>");
        }
        pair_vconn = make_unique<map<pair<int,int>, int>>(pair_vconn::load_conn_csv_or_throw(graph, opts.v_conn_csv));
    }

    run_simulation(opts, graph, pair_vconn.get());
}

void print_usage(const char* progr_name) {
    cerr << "usage: "<<progr_name;
    cerr << " -S <comma_separated_src_node_list>";
    cerr << " -e <graph_edge_list_csv_file>";
    cerr << " --halt-at-keys <int>";
    cerr << " --max-consume-prob <float>";
    cerr << " --watermark-sz <int>";
    cerr << " --block-chunks <int>";
    cerr << " --v-conn-cartel-size";
    cerr << " --v-conn-csv <conn_csv_file>";
    cerr << endl;
}

Options parse_args(int argc, char* argv[]){
    Options opts;

    auto fail = [&](string msg) -> void {
        cerr << msg << endl;
        print_usage(argv[0]);
        exit(1);
    };

    set<string> seen_flags;

    for(int i=1;i<argc;i++){
        string flag = argv[i];
        seen_flags.insert(flag);

        auto read_value = [&]() -> string{
            if(i+1>=argc) fail("flag "+flag+" requires a value");
            return argv[++i];
        };

        if(flag=="-S"){ // source node list
            string src_node_list=read_value();
            opts.src_nodes = split(src_node_list,",");
        } else if(flag=="-e"){
            opts.edges_csv = read_value();
        } else if(flag=="--verbose"){
            opts.verbose = true;
        } else if(flag=="--halt-at-keys"){
            opts.required_cnt = stoi(read_value());
        } else if(flag=="--max-consume-prob"){
            opts.max_consume_prob = stod(read_value());
        } else if(flag=="--watermark-sz"){
            opts.watermark_sz = stoi(read_value());
        } else if(flag=="--block-chunks"){
            opts.block_chunks = stoi(read_value());
        } else if(flag=="--v-conn-cartel-size"){
            opts.v_conn_cartel_size = true;
        } else if(flag=="--v-conn-csv"){
            opts.v_conn_csv = read_value();
        } else {
            fail("unknown flag "+flag);
        }

    }

    auto mandatory_flag = [&](string flag){
        if(seen_flags.count(flag)>0) return;
        fail("flag "+flag+" is mandatory");
    };

    mandatory_flag("-S");
    mandatory_flag("-e");

    return opts;
}
