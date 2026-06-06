#pragma once

#include <cstdlib>
#include <functional>
#include <iostream>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

#include "graphs.hpp"

using namespace std;

struct ParsedArg {
    string_view flag;
    string_view inline_value;
    bool has_inline_value = false;
};

inline ParsedArg split_flag_arg(string_view arg) {
    const size_t eq = arg.find('=');
    if (eq == string_view::npos) {
        return ParsedArg{arg, {}, false};
    }
    return ParsedArg{arg.substr(0, eq), arg.substr(eq + 1), true};
}

inline bool flag_is(string_view flag, string_view long_name, string_view short_name) {
    if (flag == long_name) {
        return true;
    }
    return !short_name.empty() && flag == short_name;
}

class ArgParser {
public:
    using UsageFn = function<void(const char *)>;

    ArgParser(int argc, char **argv, UsageFn usage)
        : argc_(argc), argv_(argv), usage_(std::move(usage)) {}

    static bool is_help(string_view flag) {
        return flag == "--help" || flag == "-h";
    }

    void exit_if_help(string_view flag) const {
        if (is_help(flag)) {
            usage_(argv_[0]);
            exit(0);
        }
    }

    [[noreturn]] void fail(const string &msg) const {
        cerr << msg << endl;
        usage_(argv_[0]);
        exit(1);
    }

    string require_value(int &i, string_view flag, const ParsedArg &parsed) const {
        if (parsed.has_inline_value) {
            if (parsed.inline_value.empty()) {
                fail("Missing value for " + string(flag));
            }
            return string(parsed.inline_value);
        }
        if (i + 1 >= argc_) {
            fail("Missing value for " + string(flag));
        }
        return argv_[++i];
    }

private:
    int argc_;
    char **argv_;
    UsageFn usage_;
};

struct WalkCliOpts {
    string src_node;
    string tgt_node;
    string graph = "geant";
    string edges_csv;
    string rw_variant = "HS";
    int no_of_runs = 10000;
};

struct WalkFlagOpts {
    bool include_runs = true;
    bool include_graph = true;
    bool endpoints_optional = false;
};

class CliParser {
public:
    using FlagHandler = function<void(CliParser &, int &, const ParsedArg &)>;

    CliParser(int argc, char **argv)
        : argc_(argc),
          argv_(argv),
          args_(argc, argv, [this](const char *prog) { print_usage(prog); }) {}

    void note_usage(
        string_view long_name,
        string_view short_name,
        string_view metavar,
        bool required
    ) {
        ostringstream part;
        part << (required ? "(" : "[(");
        part << long_name;
        if (!short_name.empty()) {
            part << '|' << short_name;
        }
        part << ')';
        if (!metavar.empty()) {
            part << " <" << metavar << '>';
        }
        if (!required) {
            part << ']';
        }
        usage_parts_.push_back(part.str());
    }

    void note_usage_flag(string_view long_name, string_view short_name, bool required) {
        ostringstream part;
        if (required) {
            part << '(' << long_name;
        } else {
            part << '[' << long_name;
        }
        if (!short_name.empty()) {
            part << '|' << short_name;
        }
        part << (required ? ")" : "]");
        usage_parts_.push_back(part.str());
    }

    void print_usage(const char *prog) const {
        cerr << "Usage: " << prog;
        for (const string &part : usage_parts_) {
            cerr << ' ' << part;
        }
        cerr << endl;
    }

    void reg(string_view long_name, string_view short_name, FlagHandler handler) {
        flags_.push_back(FlagSpec{long_name, short_name, std::move(handler)});
    }

    void reg(string_view long_name, FlagHandler handler) {
        reg(long_name, {}, std::move(handler));
    }

    void reg_string_impl(string_view long_name, string_view short_name, string &target) {
        reg(long_name, short_name, [&](CliParser &cli, int &i, const ParsedArg &parsed) {
            target = cli.require_value(i, parsed.flag, parsed);
        });
    }

    void reg_int_impl(string_view long_name, string_view short_name, int &target) {
        reg(long_name, short_name, [&](CliParser &cli, int &i, const ParsedArg &parsed) {
            target = stoi(cli.require_value(i, parsed.flag, parsed));
        });
    }

    void reg_bool(
        string_view long_name,
        string_view short_name,
        bool &target,
        bool required = false
    ) {
        note_usage_flag(long_name, short_name, required);
        reg(long_name, short_name, [&](CliParser &, int &, const ParsedArg &) {
            target = true;
        });
    }

    void reg_string(
        string_view long_name,
        string_view short_name,
        string &target,
        bool required = false,
        string_view metavar = "str"
    ) {
        note_usage(long_name, short_name, metavar, required);
        reg_string_impl(long_name, short_name, target);
    }

    void reg_int(
        string_view long_name,
        string_view short_name,
        int &target,
        bool required = false,
        string_view metavar = "int"
    ) {
        note_usage(long_name, short_name, metavar, required);
        reg_int_impl(long_name, short_name, target);
    }

    void reg_double(
        string_view long_name,
        string_view short_name,
        double &target,
        bool required = false,
        string_view metavar = "float"
    ) {
        note_usage(long_name, short_name, metavar, required);
        reg(long_name, short_name, [&](CliParser &cli, int &i, const ParsedArg &parsed) {
            target = stod(cli.require_value(i, parsed.flag, parsed));
        });
    }

    void reg_walk_flags(WalkCliOpts &opts, WalkFlagOpts wf = {}) {
        note_usage(
            "--src-node",
            "-s",
            "node",
            !wf.endpoints_optional
        );
        note_usage(
            "--tgt-node",
            "-t",
            "node",
            !wf.endpoints_optional
        );
        if (wf.include_graph) {
            note_usage("--graph", "-g", "nsfnet|geant|edgelist_filepath.csv", false);
        }
        note_usage("--rw-variant", "-w", "name", false);
        if (wf.include_runs) {
            note_usage("--no-of-runs", "-n", "int", false);
        }

        reg_string_impl("--src-node", "-s", opts.src_node);
        reg_string_impl("--tgt-node", "-t", opts.tgt_node);
        if (wf.include_graph) {
            reg_string_impl("--graph", "-g", opts.graph);
        }
        reg_string_impl("--rw-variant", "-w", opts.rw_variant);
        if (wf.include_runs) {
            reg_int_impl("--no-of-runs", "-n", opts.no_of_runs);
        }
    }

    void parse() {
        for (int i = 1; i < argc_; i++) {
            ParsedArg parsed = split_flag_arg(argv_[i]);
            args_.exit_if_help(parsed.flag);
            if (!dispatch(i, parsed)) {
                args_.fail("Unknown argument: " + string(parsed.flag));
            }
        }
    }

    string require_value(int &i, string_view flag, const ParsedArg &parsed) const {
        return args_.require_value(i, flag, parsed);
    }

    [[noreturn]] void fail(const string &msg) const {
        args_.fail(msg);
    }

private:
    struct FlagSpec {
        string_view long_name;
        string_view short_name;
        FlagHandler handler;
    };

    bool dispatch(int &i, const ParsedArg &parsed) {
        for (const FlagSpec &spec : flags_) {
            if (flag_is(parsed.flag, spec.long_name, spec.short_name)) {
                spec.handler(*this, i, parsed);
                return true;
            }
        }
        return false;
    }

    int argc_;
    char **argv_;
    ArgParser args_;
    vector<string> usage_parts_;
    vector<FlagSpec> flags_;
};

inline void validate_walk_endpoints(const CliParser &cli, const WalkCliOpts &opts) {
    if (opts.src_node.empty() || opts.tgt_node.empty()) {
        cli.fail("Source and target nodes are required");
    }
}

inline void validate_walk_endpoints_pair(const CliParser &cli, const WalkCliOpts &opts) {
    if (opts.src_node.empty() != opts.tgt_node.empty()) {
        cli.fail("Provide both --src-node and --tgt-node, or omit both");
    }
}

inline void resolve_walk_graph(WalkCliOpts &opts) {
    opts.edges_csv = resolve_graph_spec(opts.graph);
}

inline void validate_positive_runs(const CliParser &cli, int no_of_runs) {
    if (no_of_runs <= 0) {
        cli.fail("--no-of-runs must be > 0");
    }
}
