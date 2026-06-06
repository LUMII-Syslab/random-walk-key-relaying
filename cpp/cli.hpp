#pragma once

#include <cstdlib>
#include <functional>
#include <iostream>
#include <string>
#include <string_view>
#include <vector>

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
    string edges_csv;
    string rw_variant = "HS";
    int no_of_runs = 10000;
};

class CliParser {
public:
    using UsageFn = ArgParser::UsageFn;
    using FlagHandler = function<void(CliParser &, int &, const ParsedArg &)>;

    CliParser(int argc, char **argv, UsageFn usage)
        : argc_(argc), argv_(argv), args_(argc, argv, std::move(usage)) {}

    void reg(string_view long_name, string_view short_name, FlagHandler handler) {
        flags_.push_back(FlagSpec{long_name, short_name, std::move(handler)});
    }

    void reg(string_view long_name, FlagHandler handler) {
        reg(long_name, {}, std::move(handler));
    }

    void reg_bool(string_view long_name, string_view short_name, bool &target) {
        reg(long_name, short_name, [&](CliParser &, int &, const ParsedArg &) {
            target = true;
        });
    }

    void reg_string(string_view long_name, string_view short_name, string &target) {
        reg(long_name, short_name, [&](CliParser &cli, int &i, const ParsedArg &parsed) {
            target = cli.require_value(i, parsed.flag, parsed);
        });
    }

    void reg_int(string_view long_name, string_view short_name, int &target) {
        reg(long_name, short_name, [&](CliParser &cli, int &i, const ParsedArg &parsed) {
            target = stoi(cli.require_value(i, parsed.flag, parsed));
        });
    }

    void reg_double(string_view long_name, string_view short_name, double &target) {
        reg(long_name, short_name, [&](CliParser &cli, int &i, const ParsedArg &parsed) {
            target = stod(cli.require_value(i, parsed.flag, parsed));
        });
    }

    void reg_walk_flags(WalkCliOpts &opts, bool include_runs = true) {
        reg_string("--src-node", "-s", opts.src_node);
        reg_string("--tgt-node", "-t", opts.tgt_node);
        reg_string("--edges-csv", "-e", opts.edges_csv);
        reg_string("--rw-variant", "-w", opts.rw_variant);
        if (include_runs) {
            reg_int("--no-of-runs", "-n", opts.no_of_runs);
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
    vector<FlagSpec> flags_;
};

inline void validate_walk_endpoints(const CliParser &cli, const WalkCliOpts &opts) {
    if (opts.src_node.empty() || opts.tgt_node.empty()) {
        cli.fail("Source and target nodes are required");
    }
}

inline void validate_positive_runs(const CliParser &cli, int no_of_runs) {
    if (no_of_runs <= 0) {
        cli.fail("--no-of-runs must be > 0");
    }
}
