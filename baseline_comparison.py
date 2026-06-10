"""RF vs static Suurballe MP comparison (Sec. comparison with baseline).

Computes protected-pair coverage at design threshold tau (default 98%),
pair-mean MP-2 efficiency, and topology-wide mean RF efficiency at tau.
"""
from __future__ import annotations

import argparse
import itertools
import subprocess
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import numpy as np
import tqdm

from efficiency import (
    ALPHA,
    HOP_RUNS,
    M,
    biconnected_ordered_pairs,
    find_g,
    get_mean_hops,
    graph_specs,
    node_label,
)
from graphs import get_graph_str_adj_list
from safepairs import (
    DEFAULT_RUNS,
    HitCounts,
    cartel_exposure,
    get_hit_counts,
    pair_eligible_for_cartel,
)
from suurballe import suurballe

ROOT = Path(__file__).resolve().parent
CPP_DIR = ROOT / "cpp"

TAU = 0.98
RW_VARIANT = "HS"
CARTEL_SIZES = (1, 2, 3)


@dataclass(frozen=True)
class GraphCtx:
    label: str
    graph_arg: str
    str_adj: dict[str, list[str]]
    nx_graph: nx.Graph
    cpp_nodes: tuple[str, ...]
    name_to_idx: dict[str, int]
    int_adj: dict[int, list[int]]


def build_graph_ctx(label: str, graph_arg: str, nx_graph: nx.Graph) -> GraphCtx:
    str_adj = get_graph_str_adj_list(label)  # type: ignore[arg-type]
    nodes = tuple(sorted(str_adj))
    # Node order for hits must come from exposure --dump-hits; bootstrap with sorted.
    name_to_idx = {name: i for i, name in enumerate(nodes)}
    int_adj = _int_adj_from_names(nodes, str_adj)
    return GraphCtx(
        label=label,
        graph_arg=graph_arg,
        str_adj=str_adj,
        nx_graph=nx_graph,
        cpp_nodes=nodes,
        name_to_idx=name_to_idx,
        int_adj=int_adj,
    )


def _int_adj_from_names(
    nodes: tuple[str, ...],
    str_adj: dict[str, list[str]],
) -> dict[int, list[int]]:
    idx = {name: i for i, name in enumerate(nodes)}
    adj: dict[int, list[int]] = {i: [] for i in range(len(nodes))}
    for u_name, neighbors in str_adj.items():
        u = idx[u_name]
        for v_name in neighbors:
            v = idx[v_name]
            if v not in adj[u]:
                adj[u].append(v)
    return adj


def collect_hits(ctx: GraphCtx, no_of_runs: int) -> dict[tuple[str, str], HitCounts]:
    pairs = [(s, t) for s in ctx.cpp_nodes for t in ctx.cpp_nodes if s != t]
    out: dict[tuple[str, str], HitCounts] = {}
    for src, tgt in tqdm.tqdm(pairs, desc=f"{ctx.label} hit counts"):
        hits = get_hit_counts(src, tgt, no_of_runs, ctx.graph_arg, RW_VARIANT)
        out[(src, tgt)] = hits
    sample = next(iter(out.values()))
    cpp_nodes = sample.nodes
    if set(cpp_nodes) != set(ctx.cpp_nodes):
        raise RuntimeError(f"C++ node set mismatch on {ctx.label}")
    if cpp_nodes != ctx.cpp_nodes:
        idx = {name: i for i, name in enumerate(cpp_nodes)}
        ctx = GraphCtx(
            label=ctx.label,
            graph_arg=ctx.graph_arg,
            str_adj=ctx.str_adj,
            nx_graph=ctx.nx_graph,
            cpp_nodes=cpp_nodes,
            name_to_idx=idx,
            int_adj=_int_adj_from_names(cpp_nodes, ctx.str_adj),
        )
    return out


def precompute_mp_paths(ctx: GraphCtx) -> dict[tuple[int, int], list[list[int]]]:
    paths: dict[tuple[int, int], list[list[int]]] = {}
    n = len(ctx.cpp_nodes)
    for s in range(n):
        for t in range(n):
            if s == t:
                continue
            s_name = ctx.cpp_nodes[s]
            t_name = ctx.cpp_nodes[t]
            k = nx.node_connectivity(ctx.nx_graph, s_name, t_name)
            paths[(s, t)] = suurballe(ctx.int_adj, s, t, k)
    return paths


def mp_protects(paths: list[list[int]], cartel: frozenset[int]) -> bool:
    return any(cartel.isdisjoint(path) for path in paths)


def protection_fractions(
    ctx: GraphCtx,
    hits_by_pair: dict[tuple[str, str], HitCounts],
    mp_paths: dict[tuple[int, int], list[list[int]]],
    cartel_size: int,
    tau: float,
) -> tuple[list[float], list[float], list[float], list[float], list[dict]]:
    n = len(ctx.cpp_nodes)
    nodes = list(ctx.cpp_nodes)
    adj = [ctx.int_adj[i] for i in range(n)]

    pi_rf: list[float] = []
    pi_mp: list[float] = []
    pi_rf_minus_mp: list[float] = []
    pi_mp_minus_rf: list[float] = []
    cartel_details: list[dict] = []

    for cartel in itertools.combinations(range(n), cartel_size):
        cartel_set = frozenset(cartel)
        cartel_tuple = tuple(sorted(cartel))
        eligible = 0
        rf_prot: set[tuple[int, int]] = set()
        mp_prot: set[tuple[int, int]] = set()

        for src_name, tgt_name in itertools.product(nodes, nodes):
            if src_name == tgt_name:
                continue
            s = ctx.name_to_idx[src_name]
            t = ctx.name_to_idx[tgt_name]
            if not pair_eligible_for_cartel(s, t, cartel_set, adj):
                continue
            eligible += 1
            exposure = cartel_exposure(cartel_tuple, hits_by_pair[(src_name, tgt_name)])
            if exposure <= tau:
                rf_prot.add((s, t))
            if mp_protects(mp_paths[(s, t)], cartel_set):
                mp_prot.add((s, t))

        if eligible == 0:
            continue

        rf_only = rf_prot - mp_prot
        mp_only = mp_prot - rf_prot
        frac_rf = len(rf_prot) / eligible
        frac_mp = len(mp_prot) / eligible
        frac_rf_minus_mp = len(rf_only) / eligible
        frac_mp_minus_rf = len(mp_only) / eligible

        pi_rf.append(frac_rf)
        pi_mp.append(frac_mp)
        pi_rf_minus_mp.append(frac_rf_minus_mp)
        pi_mp_minus_rf.append(frac_mp_minus_rf)

        cartel_names = tuple(ctx.cpp_nodes[i] for i in cartel)
        cartel_details.append(
            {
                "cartel": cartel_names,
                "eligible": eligible,
                "pi_rf": frac_rf,
                "pi_mp": frac_mp,
                "pi_rf_minus_mp": frac_rf_minus_mp,
                "pi_mp_minus_rf": frac_mp_minus_rf,
                "rf_only_count": len(rf_only),
            }
        )

    return pi_rf, pi_mp, pi_rf_minus_mp, pi_mp_minus_rf, cartel_details


def mean_pct(values: list[float]) -> float:
    if not values:
        return 0.0
    return 100.0 * float(np.mean(values))


def format_pct(x: float) -> str:
    return f"{x:.2f}\\%"


def summarize_protection(
    ctx: GraphCtx,
    hits_by_pair: dict[tuple[str, str], HitCounts],
    mp_paths: dict[tuple[int, int], list[list[int]]],
    tau: float,
) -> dict[int, dict[str, float]]:
    rows: dict[int, dict[str, float]] = {}
    best_m3: dict | None = None

    for cartel_size in CARTEL_SIZES:
        pi_rf, pi_mp, pi_rf_m_mp, pi_mp_m_rf, details = protection_fractions(
            ctx, hits_by_pair, mp_paths, cartel_size, tau
        )
        rows[cartel_size] = {
            "pi_rf": mean_pct(pi_rf),
            "pi_mp": mean_pct(pi_mp),
            "pi_rf_minus_mp": mean_pct(pi_rf_m_mp),
            "pi_mp_minus_rf": mean_pct(pi_mp_m_rf),
            "n_cartels": len(pi_rf),
        }
        if cartel_size == 3:
            best = max(details, key=lambda d: d["pi_rf_minus_mp"])
            best_m3 = best

    return rows, best_m3


def mean_mp2_efficiency(ctx: GraphCtx) -> float:
    pairs = biconnected_ordered_pairs(ctx.nx_graph)
    etas: list[float] = []
    for src_name, tgt_name in pairs:
        s = ctx.name_to_idx[src_name]
        t = ctx.name_to_idx[tgt_name]
        paths = suurballe(ctx.int_adj, s, t, 2)
        hop_sum = sum(len(path) - 1 for path in paths)
        etas.append(100.0 / hop_sum)
    return float(np.mean(etas))


def mean_rf_efficiency_at_tau(ctx: GraphCtx, tau: float) -> float:
    rho_tau = find_g(M, tau, ALPHA) / M
    pairs = biconnected_ordered_pairs(ctx.nx_graph)
    etas: list[float] = []
    for src_name, tgt_name in pairs:
        mean_hops = get_mean_hops(
            src_name,
            tgt_name,
            ctx.graph_arg,
            RW_VARIANT,
            erase_loops=True,
            no_of_runs=HOP_RUNS,
        )
        etas.append(100.0 * rho_tau / mean_hops)
    return float(np.mean(etas))


def print_protection_table(
    all_rows: dict[str, dict[int, dict[str, float]]],
    tau: float,
) -> None:
    print(f"\nProtection table (tau={100 * tau:.0f}%):")
    print(
        f"{'Graph':>8} {'m':>2}  {'pi_RF':>8} {'pi_MP':>8} "
        f"{'RF\\MP':>8} {'MP\\RF':>8} {'#cartels':>8}"
    )
    for graph_label, rows in all_rows.items():
        for m in CARTEL_SIZES:
            r = rows[m]
            print(
                f"{graph_label:>8} {m:>2}  "
                f"{r['pi_rf']:7.2f}% {r['pi_mp']:7.2f}% "
                f"{r['pi_rf_minus_mp']:7.2f}% {r['pi_mp_minus_rf']:7.2f}% "
                f"{int(r['n_cartels']):>8}"
            )

    print("\nLaTeX rows:")
    for graph_label in ("NSFNET", "GEANT"):
        if graph_label not in all_rows:
            continue
        rows = all_rows[graph_label]
        for m in CARTEL_SIZES:
            r = rows[m]
            gl = "G\\'EANT" if graph_label == "GEANT" else graph_label
            print(
                f"{gl}    & {m} & {format_pct(r['pi_rf'])} & {format_pct(r['pi_mp'])} & "
                f"{format_pct(r['pi_rf_minus_mp'])} & {format_pct(r['pi_mp_minus_rf'])} \\\\"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tau", type=float, default=TAU)
    parser.add_argument("--runs", type=int, default=DEFAULT_RUNS)
    args = parser.parse_args()

    subprocess.run(["make", "-C", str(CPP_DIR), "exposure", "hops"], check=True)

    all_protection: dict[str, dict[int, dict[str, float]]] = {}
    best_cartels: dict[str, dict] = {}
    mp2: dict[str, float] = {}
    rf_tau: dict[str, float] = {}

    for spec in graph_specs(include_generated=False):
        ctx = build_graph_ctx(spec.label, spec.graph_arg, spec.nx_graph)
        hits = collect_hits(ctx, args.runs)
        ctx = GraphCtx(
            label=ctx.label,
            graph_arg=ctx.graph_arg,
            str_adj=ctx.str_adj,
            nx_graph=ctx.nx_graph,
            cpp_nodes=next(iter(hits.values())).nodes,
            name_to_idx={name: i for i, name in enumerate(next(iter(hits.values())).nodes)},
            int_adj=_int_adj_from_names(
                next(iter(hits.values())).nodes, ctx.str_adj
            ),
        )
        mp_paths = precompute_mp_paths(ctx)
        rows, best_m3 = summarize_protection(ctx, hits, mp_paths, args.tau)
        all_protection[spec.label] = rows
        best_cartels[spec.label] = best_m3
        mp2[spec.label] = mean_mp2_efficiency(ctx)
        rf_tau[spec.label] = mean_rf_efficiency_at_tau(ctx, args.tau)

    print_protection_table(all_protection, args.tau)

    print(f"\nEfficiency comparison (tau={100 * args.tau:.0f}%):")
    print(f"{'Graph':>8}  {'eta_RF':>8}  {'eta_MP2':>8}  {'RF/MP':>6}")
    for graph_label in ("NSFNET", "GEANT"):
        ratio = rf_tau[graph_label] / mp2[graph_label]
        print(
            f"{graph_label:>8}  {rf_tau[graph_label]:8.2f}%  "
            f"{mp2[graph_label]:8.2f}%  {ratio:6.2f}"
        )

    print("\nLaTeX efficiency-comparison rows:")
    for graph_label in ("NSFNET", "GEANT"):
        gl = "G\\'EANT" if graph_label == "GEANT" else graph_label
        ratio = rf_tau[graph_label] / mp2[graph_label]
        print(
            f"{gl}    & {rf_tau[graph_label]:.2f} & {mp2[graph_label]:.1f} & "
            f"{ratio:.1f} \\\\"
        )

    for graph_label, best in best_cartels.items():
        if best is None:
            continue
        print(f"\nWorst RF\\MP cartel on {graph_label} (m=3):")
        print(f"  cartel={best['cartel']}")
        print(f"  eligible={best['eligible']}")
        print(
            f"  pi_RF={100 * best['pi_rf']:.2f}%  "
            f"pi_MP={100 * best['pi_mp']:.2f}%  "
            f"pi_RF\\MP={100 * best['pi_rf_minus_mp']:.2f}%  "
            f"({best['rf_only_count']} of {best['eligible']} pairs)"
        )


if __name__ == "__main__":
    main()
