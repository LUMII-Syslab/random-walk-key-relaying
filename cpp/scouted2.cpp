#include <iostream>
#include <queue>
#include <vector>
#include "graph.hpp"
#include "utils.hpp"
#include "walk.hpp"

using namespace std;

const double SCOUTS_PER_SECONDS = 4;

struct Options{
    string edges_csv = "";
    vector<string> src_nodes;
    bool verbose;

    void print(){
        cout<<"edges_csv: "<<edges_csv<<endl;
        cout<<"src_nodes: "<<join(src_nodes, ",")<<endl;
    }
};

enum class EventType {
    EmitScout,
    ScoutForward,
    ScoutReturn,
    ChunkForward,
};

struct Event{
    double time;
    EventType type;
    
    // emit scout event
    int origin;
};

bool operator<(const Event& lhs, const Event& rhs){
    return lhs.time < rhs.time;
}

void run_simulation(const Options& opts, const Graph& graph){
    priority_queue<Event> pq;
    
    for(string src: opts.src_nodes){
        int origin = graph.node_index(src);
        pq.push(Event{0.0,EventType::EmitScout,origin});
    }
    
    while(pq.size()>0){
        Event e = pq.top();
        pq.pop();
        
        if(e.type == EventType::EmitScout){
            double next_occurrence = e.time + 1/SCOUTS_PER_SECONDS;
            pq.push(Event{next_occurrence,EventType::EmitScout,e.origin});
            
            // choose random neighbor
            // create a new random walk token
            
            continue;
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
