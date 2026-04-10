#include <cctype>
#include <iostream>
#include <queue>
#include <sstream>
#include <string>
#include <type_traits>
#include <string_view>
#include <variant>
#include <vector>
#include <memory>

#include "graph.hpp"
#include "walk.hpp"
using namespace std;

/**
 * Mirrors helpers/compute.py ProactiveRecvChunkEvent / ProactiveKeyEstablishedEvent.
 */
struct ReportedRecvChunkEvent {
    double time = 0.0;
    string src;
    string tgt;
    vector<string> path;
};

struct ReportedKeyEstablEvent {
    double time = 0.0;
    string src;
    string tgt;
    int key_count = 0;
};

using ReportedEvent = variant<ReportedRecvChunkEvent, ReportedKeyEstablEvent>;

struct InternalOtpAvailableEvent {
    double time = 0.0;
    int from = -1;
    int to = -1;
};

/** Internal sim events — priority queue left empty until scheduling is implemented. */
struct InternalEvent {
    double time = 0.0;
};

struct InternalEventGreater {
    bool operator()(const InternalEvent &a, const InternalEvent &b) const {
        return a.time > b.time;
    }
};

/**
 * Mirrors helpers/compute.py ProactiveSimParams (graph via stdin or --edges-csv).
 * Fixed assumptions (docstring there): chunk 256 bits, SKR 1000 b/s, unlimited buffers,
 * latency 5 ms, TTL 1–100 — not represented as CLI flags yet.
 */
struct Options {
    vector<string> src_nodes;
    string rw_variant;
    double duration_s = 0.0;
    int sieve_table_sz = 32;
    int watermark_sz = 16;
    string edges_csv = "";
    int relay_buff_sz = 100; // fifo relay buffer size
};

void print_usage(const char *prog_name);
Options parse_args(int argc, char **argv);
static void print_proactive_output(const Options &opts, const vector<ReportedEvent> &reported, ostream &out);

unique_ptr<RwToken> make_base_token(const string &rw_variant, int src_idx, int tgt_idx, int seed, int node_count) {
    if (rw_variant == "R") return make_unique<RToken>(src_idx, tgt_idx, seed);
    if (rw_variant == "NB") return make_unique<NbToken>(src_idx, tgt_idx, seed);
    if (rw_variant == "LRV") return make_unique<LrvToken>(src_idx, tgt_idx, seed);
    if (rw_variant == "NC") return make_unique<NcToken>(src_idx, tgt_idx, seed, node_count);
    if (rw_variant == "HS") return make_unique<HsToken>(src_idx, tgt_idx, seed);
    return nullptr;
}

vector<ReportedEvent> run_simulation(const Options &opts, Graph &graph) {
    priority_queue<InternalEvent, vector<InternalEvent>, InternalEventGreater> internal_pq;
    (void)internal_pq;
    (void)graph;
    static int seed_offset = 0;

    for (int i=0;i<opts.relay_buff_sz;i++) {
        seed_offset++;
        RwToken *token = make_base_token(opts.rw_variant, opts.src_nodes[0], -1, seed_offset, graph.node_count());
        
    }

    vector<ReportedEvent> reported;
    const string &p = opts.src_nodes.front();
    reported.push_back(ReportedKeyEstablEvent{0.0, p, p, 0});
    reported.push_back(ReportedRecvChunkEvent{0.0, p, p, {}});
    return reported;
}


static void print_event_line(const ReportedEvent &ev, ostream &out) {
    visit(
        [&](auto &&e) {
            using T = decay_t<decltype(e)>;
            if constexpr (is_same_v<T, ReportedKeyEstablEvent>) {
                out << "key_establ " << e.time << " " << e.src << " " << e.tgt << " " << e.key_count << endl;
            } else {
                out << "recv_chunk " << e.time << " " << e.src << " " << e.tgt;
                for (const string &hop : e.path) {
                    out << " " << hop;
                }
                out << endl;
            }
        },
        ev);
}

static void print_proactive_output(const Options &opts, const vector<ReportedEvent> &reported, ostream &out) {
    auto join_src = [&]() -> string {
        string s;
        for (size_t i = 0; i < opts.src_nodes.size(); ++i) {
            if (i) s += ',';
            s += opts.src_nodes[i];
        }
        return s;
    };

    out << "src_nodes: " << join_src() << endl;
    out << "rw_variant: " << opts.rw_variant << endl;
    out << "duration_s: " << opts.duration_s << endl;
    out << "sieve_table_sz: " << opts.sieve_table_sz << endl;
    out << "watermark_sz: " << opts.watermark_sz << endl;
    out << "watermark_time: 0" << endl;
    out << "event_count: " << reported.size() << endl;
    for (const ReportedEvent &ev : reported) {
        print_event_line(ev, out);
    }
    out << endl;
}

int main(int argc, char **argv) {
    try {
        Options opts = parse_args(argc, argv);
        Graph graph = opts.edges_csv.empty() ? Graph(cin) : Graph(opts.edges_csv);
        for (const string &name : opts.src_nodes) {
            graph.node_index(name);
        }
        vector<ReportedEvent> reported = run_simulation(opts, graph);
        print_proactive_output(opts, reported, cout);
        return 0;
    } catch (const exception &e) {
        cerr << e.what() << endl;
        return 1;
    }
}

static string trim(string s) {
    while (!s.empty() && isspace(static_cast<unsigned char>(s.back()))) s.pop_back();
    size_t i = 0;
    while (i < s.size() && isspace(static_cast<unsigned char>(s[i]))) i++;
    return s.substr(i);
}

static vector<string> parse_src_nodes_csv(const string &s) {
    vector<string> out;
    stringstream ss(s);
    string part;
    while (getline(ss, part, ',')) {
        part = trim(part);
        if (!part.empty()) out.push_back(part);
    }
    return out;
}

void print_usage(const char *prog_name) {
    cerr << "Usage: " << prog_name
         << " (--src-nodes|-S) <n1,n2,...> (--rw-variant|-w) <name> "
            "(--duration-s|-d) <seconds> "
            "[--sieve-table-sz <int>] [--watermark-sz <int>] "
            "[(--edges-csv|-e) <path>]" << endl;
}

static bool valid_rw_variant(const string &w) {
    return w == "R" || w == "NB" || w == "LRV" || w == "NC" || w == "HS";
}

Options parse_args(int argc, char **argv) {
    Options opts;
    auto fail = [&](const string &msg) -> void {
        cerr << msg << endl;
        print_usage(argv[0]);
        exit(1);
    };

    auto require_value = [&](int &i, string_view flag, bool has_inline, string_view inline_value) -> string {
        if (has_inline) {
            if (inline_value.empty()) {
                fail("Missing value for " + string(flag));
            }
            return string(inline_value);
        }
        if (i + 1 >= argc) {
            fail("Missing value for " + string(flag));
        }
        return argv[++i];
    };

    bool have_src_nodes = false;
    bool have_rw = false;
    bool have_duration = false;

    for (int i = 1; i < argc; i++) {
        string_view arg = argv[i];
        if (arg == "--help" || arg == "-h") {
            print_usage(argv[0]);
            exit(0);
        }

        size_t eq_pos = arg.find('=');
        bool has_inline = eq_pos != string_view::npos;
        string_view flag = has_inline ? arg.substr(0, eq_pos) : arg;
        string_view inline_value = has_inline ? arg.substr(eq_pos + 1) : string_view{};

        if (flag == "--src-nodes" || flag == "-S") {
            string raw = require_value(i, flag, has_inline, inline_value);
            opts.src_nodes = parse_src_nodes_csv(raw);
            have_src_nodes = true;
        } else if (flag == "--rw-variant" || flag == "-w") {
            opts.rw_variant = require_value(i, flag, has_inline, inline_value);
            have_rw = true;
        } else if (flag == "--duration-s" || flag == "-d") {
            opts.duration_s = stod(require_value(i, flag, has_inline, inline_value));
            have_duration = true;
        } else if (flag == "--sieve-table-sz") {
            opts.sieve_table_sz = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--watermark-sz") {
            opts.watermark_sz = stoi(require_value(i, flag, has_inline, inline_value));
        } else if (flag == "--edges-csv" || flag == "-e") {
            opts.edges_csv = require_value(i, flag, has_inline, inline_value);
        } else {
            fail("Unknown argument: " + string(arg));
        }
    }

    if (!have_src_nodes || opts.src_nodes.empty()) {
        fail("Non-empty --src-nodes is required (comma-separated node names)");
    }
    if (!have_rw || opts.rw_variant.empty()) {
        fail("--rw-variant is required");
    }
    if (!valid_rw_variant(opts.rw_variant)) {
        fail("Unknown random walk variant: " + opts.rw_variant);
    }
    if (!have_duration) {
        fail("--duration-s is required");
    }
    if (opts.duration_s <= 0.0) {
        fail("--duration-s must be > 0");
    }
    if (opts.sieve_table_sz <= 0) {
        fail("--sieve-table-sz must be > 0");
    }
    if (opts.watermark_sz <= 0) {
        fail("--watermark-sz must be > 0");
    }
    return opts;
}
