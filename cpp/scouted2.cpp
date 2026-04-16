#include <iostream>
#include <map>
#include <memory>
#include <queue>
#include <random>
#include <vector>
#include "graph.hpp"
#include "utils.hpp"
#include "walk.hpp"

using namespace std;

const double SCOUTS_PER_SECONDS = 4;
const double CLASSICAL_DELAY_MS = 5;
const double QKD_SKR_BITS_P_S = 1000;
const int CHUNK_SIZE_BITS = 256;

mt19937 rng(2026);

struct Options{
    string edges_csv = "";
    vector<string> src_nodes;
    bool verbose;
    int watermark_sz = 128;
    uint ttl = 100;
    int max_wait_time_s = 2;

    void print(){
        cout<<"edges_csv: "<<edges_csv<<endl;
        cout<<"src_nodes: "<<join(src_nodes, ",")<<endl;
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

bool consume(int keys_in_buff, int watermark, int hop_count, int ttl){
    if(keys_in_buff>=watermark) return false;
    if(rng()%2==0) return false;
    assert(hop_count<=ttl);
    double b = (double)keys_in_buff/(double)watermark;
    double t = (double)(ttl-hop_count)/(double)ttl;
    double p = 1 - b*t;
    double r = (double)(rng()-rng.min())/(double)(rng.max()-rng.min());
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

void run_simulation(const Options& opts, const Graph& graph){
    priority_queue<Event> pq;

    for(string src: opts.src_nodes){
        int origin = graph.node_index(src);
        pq.push(Event{0.0,EventType::EmitScout,origin,-1,-1,nullptr,{},-1,0});
    }

    map<pair<int,int>,int> established_keys;
    map<pair<int,int>,int> chunks_received;
    map<pair<int,int>, map<int,int>> chunk_traversed;

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
            bool wait_time_ok = predict_wait_time(e.time, e.sender, e.receiver)<=opts.max_wait_time_s;
            bool ttl_ok = 1 <= opts.ttl;
            if(wait_time_ok&&ttl_ok)
                pq.push(Event{arrives_at,EventType::ScoutForward,e.origin,e.origin,ngh,token,{e.origin,ngh},-1,0});
            continue;
        }

        if(e.type == EventType::ScoutForward){
            if(e.receiver!=e.origin&&consume(established_keys[{e.origin,e.receiver}], opts.watermark_sz, e.history.size()-1, opts.ttl)){
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
            bool wait_time_ok = predict_wait_time(e.time, e.sender, e.receiver)<=opts.max_wait_time_s;
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
            double wait_time = max(e.wait,enqueue_on_link(e.time, e.receiver, nxt));
            double arrives_at = e.time + CLASSICAL_DELAY_MS/1000.0;
            pq.push(Event{arrives_at,EventType::ScoutReturn,e.origin,e.receiver,nxt,nullptr,e.history,e.target,wait_time});
            continue;
        }
        
        if(e.type == EventType::ChunkReceived){
            chunks_received[{e.origin, e.target}]++;
            for(int x: e.history){
                chunk_traversed[{e.origin, e.target}][x]++;
            }
            if(chunks_received[{e.origin, e.target}]==opts.watermark_sz){
                chunks_received[{e.origin, e.target}]=0;
                int max_chunks_traversed = 0;
                int max_chunks_traversed_node = -1;
                for(auto [node, cnt]: chunk_traversed[{e.origin, e.target}]){
                    if(node==e.origin||node==e.target) continue;
                    if (cnt>max_chunks_traversed){
                        max_chunks_traversed = cnt;
                        max_chunks_traversed_node = node;
                    }
                }
                chunk_traversed[{e.origin, e.target}] = map<int,int>();
                int honesty = opts.watermark_sz - max_chunks_traversed;
                established_keys[{e.origin, e.target}]+=honesty;
                if(opts.verbose){
                    string node_name = "-";
                    if (max_chunks_traversed_node!=-1) node_name = graph.node_name(max_chunks_traversed_node);
                    cout<<"keys "<<honesty<<" "<<graph.node_name(e.origin)<<" "<<graph.node_name(e.target)<<" "<<node_name<<" "<<max_chunks_traversed<<endl;
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

    run_simulation(opts, graph);
}

void print_usage(const char* progr_name) {
    cerr << "usage: "<<progr_name;
    cerr << " -S <comma_separated_src_node_list>";
    cerr << " -e <graph_edge_list_csv_file>";
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
