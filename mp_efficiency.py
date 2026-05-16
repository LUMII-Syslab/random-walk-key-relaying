"""Compute the Table 10 Suurballe MP-2 efficiency column.

For each graph, this experiment averages

    eta_MP,2(s,t) = 1 / (L1 + L2)

over biconnected ordered pairs, where L1 and L2 are the hop counts of the two
minimum-total-length internally node-disjoint paths returned by Suurballe.
The implementation iterates unordered pairs because the graphs are undirected
and the minimum total path length is symmetric.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from itertools import combinations

import networkx as nx
import numpy as np
from numba import njit
from tqdm import tqdm

from readgraphcsv import Graph, read_graph, synthetic_graph_snapshot
from rwvariants import _numba_adj, _rw_HS
from suurballe import suurballe


GSTAR_99_99_M1024_CHI95 = 27
RF_HS_LE_PERCENT = {
    "NSFNET": 30.0,
    "G'EANT": 11.0,
    "Generated": 4.4,
}

LATEX_LABEL = {
    "G'EANT": r"G\'EANT",
}


@dataclass(frozen=True)
class MPEfficiencyRow:
    label: str
    unordered_pairs: int
    ordered_pairs: int
    eta_percent: float
    rf_percent: float | None
    rf_design95_percent: float | None

    @property
    def rf_over_mp(self) -> float | None:
        if self.rf_percent is None:
            return None
        return self.rf_percent / self.eta_percent


def load_graph(name: str) -> tuple[str, Graph]:
    if name in ("nsfnet", "geant", "secoqc"):
        label = "G'EANT" if name == "geant" else name.upper()
        return label, read_graph(name)
    if name.startswith("generated"):
        _, _, n_str = name.partition(":")
        n = int(n_str) if n_str else 99
        label = "Generated" if n == 99 else f"Generated({n})"
        return label, synthetic_graph_snapshot(n)
    raise ValueError(f"unknown graph: {name}")


def biconnected_unordered_pairs(graph_nx: nx.Graph) -> list[tuple[int, int]]:
    node_bcc_ids: dict[int, set[int]] = {v: set() for v in graph_nx.nodes}
    for bcc_id, bcc in enumerate(nx.biconnected_components(graph_nx)):
        if len(bcc) < 3:
            continue
        for node in bcc:
            node_bcc_ids[node].add(bcc_id)

    return [
        (s, t)
        for s, t in combinations(graph_nx.nodes, 2)
        if not node_bcc_ids[s].isdisjoint(node_bcc_ids[t])
    ]


@njit(cache=True)
def _loop_erased_hop_count(path: np.ndarray, node_count: int) -> int:
    first_pos = np.full(node_count, -1, dtype=np.int64)
    stack = np.empty(len(path), dtype=np.int64)
    kept = 0
    for node in path:
        node = int(node)
        pos = first_pos[node]
        if pos >= 0:
            for idx in range(pos + 1, kept):
                first_pos[stack[idx]] = -1
            kept = pos + 1
        else:
            first_pos[node] = kept
            stack[kept] = node
            kept += 1
    return kept - 1


@njit(cache=True)
def _mean_inverse_hs_le_hops_for_ordered_pairs(adj, pairs: np.ndarray,
                                               runs: int) -> float:
    total = 0.0
    count = 0
    node_count = len(adj)
    for pair_idx in range(pairs.shape[0]):
        s = int(pairs[pair_idx, 0])
        t = int(pairs[pair_idx, 1])
        for seed in range(runs):
            path = _rw_HS(adj, s, t, seed)
            hops = _loop_erased_hop_count(path, node_count)
            if hops > 0:
                total += 1.0 / hops
                count += 1
    return total / count


def rf_design95_efficiency_percent(graph: Graph, ordered_pairs: np.ndarray,
                                   runs: int) -> float:
    mean_inverse_hops = _mean_inverse_hs_le_hops_for_ordered_pairs(
        _numba_adj(graph),
        ordered_pairs,
        runs,
    )
    return 100.0 * (GSTAR_99_99_M1024_CHI95 / 1024.0) * mean_inverse_hops


def mp2_efficiency_row(label: str, graph: Graph, runs: int | None) -> MPEfficiencyRow:
    graph_nx = graph.to_nx()
    pairs = biconnected_unordered_pairs(graph_nx)
    if not pairs:
        raise ValueError(f"{label} has no biconnected pairs")

    eta_sum = 0.0
    for s, t in pairs:
        paths = suurballe(graph, s, t, 2)
        total_hops = sum(len(path) - 1 for path in paths)
        eta_sum += 1.0 / total_hops

    eta_percent = 100.0 * eta_sum / len(pairs)
    ordered_pairs = np.array(
        [(s, t) for s, t in pairs] + [(t, s) for s, t in pairs],
        dtype=np.int64,
    )
    rf_design95_percent = (
        None
        if runs is None
        else rf_design95_efficiency_percent(graph, ordered_pairs, runs)
    )
    return MPEfficiencyRow(
        label=label,
        unordered_pairs=len(pairs),
        ordered_pairs=2 * len(pairs),
        eta_percent=eta_percent,
        rf_percent=RF_HS_LE_PERCENT.get(label),
        rf_design95_percent=rf_design95_percent,
    )


def format_percent(value: float) -> str:
    if value >= 10:
        return f"{value:.1f}"
    return f"{value:.2f}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "graphs",
        nargs="*",
        default=["nsfnet", "geant", "generated"],
        help="graph names; use generated:N for synthetic snapshots",
    )
    parser.add_argument(
        "--rf-design-runs",
        type=int,
        default=None,
        help=(
            "if set, also estimate HS loop-erased RF efficiency at chi=95%% "
            "using this many walks per ordered pair"
        ),
    )
    args = parser.parse_args()

    rows = [
        mp2_efficiency_row(*load_graph(name), args.rf_design_runs)
        for name in tqdm(args.graphs, desc="graphs")
    ]

    print("Graph, unordered pairs, ordered pairs, eta_MP,2 [%], RF/MP, RF@95 [%], RF@95/MP")
    for row in rows:
        ratio = "n/a" if row.rf_over_mp is None else f"{row.rf_over_mp:.2f}"
        rf95 = (
            "n/a"
            if row.rf_design95_percent is None
            else f"{row.rf_design95_percent:.6f}"
        )
        rf95_ratio = (
            "n/a"
            if row.rf_design95_percent is None
            else f"{row.rf_design95_percent / row.eta_percent:.2f}"
        )
        print(
            f"{row.label}, {row.unordered_pairs}, {row.ordered_pairs}, "
            f"{row.eta_percent:.6f}, {ratio}, {rf95}, {rf95_ratio}"
        )

    print("\nLaTeX rows:")
    for row in rows:
        rf = "TBD" if row.rf_percent is None else format_percent(row.rf_percent)
        ratio = "TBD" if row.rf_over_mp is None else f"{row.rf_over_mp:.2f}"
        label = LATEX_LABEL.get(row.label, row.label)
        print(
            f"{label} & {rf} & {format_percent(row.eta_percent)} & "
            f"{ratio} \\\\"
        )


if __name__ == "__main__":
    main()
