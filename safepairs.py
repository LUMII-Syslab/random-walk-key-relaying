"""Cartel affected-pair analysis for GÉANT (Table tab:cartel-underestimation).

For each ordered source-target pair, runs loop-erased HS random walks via
``cpp/build/exposure --dump-hits`` and caches marginal hit counts (single,
pair, triple). Inclusion-exclusion on those marginals yields per-cartel
exposure without re-running Monte Carlo.

For each cartel size and design-exposure threshold, reports median, average,
and maximum of |A(C, χ̄)| / |E(C)| over eligible unordered cartels C.
"""
from __future__ import annotations

import itertools
import json
import os
import re
import subprocess
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import tqdm
from joblib import Memory

from graphs import GEANT, get_graph_nx_graph

ROOT = Path(__file__).resolve().parent
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "random-walk-relaying")
memory = Memory(location=CACHE_DIR, verbose=0)

THRESHOLDS = [0.75, 0.80, 0.85, 0.90, 0.95, 0.97, 0.98, 0.99]
CARTEL_SIZES = (2, 3)
DEFAULT_RUNS = 10_000
GRAPH = "geant"
RW_VARIANT = "HS"


@dataclass(frozen=True)
class HitCounts:
    runs: int
    nodes: tuple[str, ...]
    single: np.ndarray
    pair: np.ndarray
    triple: dict[tuple[int, int, int], int]

    @property
    def n(self) -> int:
        return len(self.nodes)

    def node_index(self) -> dict[str, int]:
        return {name: idx for idx, name in enumerate(self.nodes)}


def _parse_hit_output(stdout: str) -> HitCounts:
    runs = int(re.search(r"^runs:\s*(\d+)", stdout, re.M).group(1))
    n = int(re.search(r"^n:\s*(\d+)", stdout, re.M).group(1))
    nodes = tuple(re.search(r"^nodes:(.*)$", stdout, re.M).group(1).split())
    single = np.fromstring(
        re.search(r"^single:(.*)$", stdout, re.M).group(1), sep=" ", dtype=np.int64
    )
    pair_flat = np.fromstring(
        re.search(r"^pair:(.*)$", stdout, re.M).group(1), sep=" ", dtype=np.int64
    )
    pair = np.zeros((n, n), dtype=np.int64)
    idx = 0
    for u in range(n):
        for v in range(u + 1, n):
            pair[u, v] = pair_flat[idx]
            idx += 1
    triple: dict[tuple[int, int, int], int] = {}
    for line in stdout.splitlines():
        if not line.startswith("triple: "):
            continue
        u, v, w, count = line.split()[1:]
        triple[(int(u), int(v), int(w))] = int(count)
    return HitCounts(runs=runs, nodes=nodes, single=single, pair=pair, triple=triple)


@memory.cache
def get_hit_counts(src: str, tgt: str, no_of_runs: int, graph: str, rw_variant: str) -> HitCounts:
    result = subprocess.run(
        [
            "./build/exposure",
            "-s", src,
            "-t", tgt,
            "-g", graph,
            "-w", rw_variant,
            "-n", str(no_of_runs),
            "--dump-hits",
        ],
        capture_output=True,
        text=True,
        cwd=ROOT / "cpp",
        check=True,
    )
    return _parse_hit_output(result.stdout)


def cartel_union_hits(cartel: tuple[int, ...], hits: HitCounts) -> int:
    if len(cartel) == 1:
        return int(hits.single[cartel[0]])
    u, v = sorted(cartel[:2])
    union_hits = int(hits.single[cartel[0]] + hits.single[cartel[1]] - hits.pair[u, v])
    if len(cartel) == 3:
        a, b, c = sorted(cartel)
        tri = hits.triple.get((a, b, c), 0)
        union_hits += int(
            hits.single[c]
            - hits.pair[min(a, c), max(a, c)]
            - hits.pair[min(b, c), max(b, c)]
            + tri
        )
    return union_hits


def cartel_exposure(cartel: tuple[int, ...], hits: HitCounts) -> float:
    return cartel_union_hits(cartel, hits) / hits.runs


def pair_eligible_for_cartel(
    src: int,
    tgt: int,
    cartel: frozenset[int],
    adj: list[list[int]],
) -> bool:
    if src in cartel or tgt in cartel:
        return False
    blocked = cartel
    seen = {src}
    q = deque([src])
    while q:
        u = q.popleft()
        if u == tgt:
            return True
        for v in adj[u]:
            if v not in blocked and v not in seen:
                seen.add(v)
                q.append(v)
    return False


def collect_all_hits(
    nodes: tuple[str, ...],
    no_of_runs: int,
) -> dict[tuple[str, str], HitCounts]:
    pairs = [(s, t) for s in nodes for t in nodes if s != t]
    out: dict[tuple[str, str], HitCounts] = {}
    for src, tgt in tqdm.tqdm(pairs, desc="LERW hit counts"):
        out[(src, tgt)] = get_hit_counts(src, tgt, no_of_runs, GRAPH, RW_VARIANT)
    return out


def build_index_maps(
    nodes: tuple[str, ...],
) -> tuple[dict[str, int], list[list[int]]]:
    """Index order must match ``exposure --dump-hits`` (edges.csv first-seen order)."""
    g = get_graph_nx_graph("GEANT")
    missing = [n for n in nodes if n not in g]
    if missing:
        raise RuntimeError(f"nodes missing from GEANT graph: {missing}")
    idx = {name: i for i, name in enumerate(nodes)}
    adj: list[list[int]] = [[] for _ in nodes]
    for u_name, v_name in g.edges():
        u, v = idx[u_name], idx[v_name]
        adj[u].append(v)
        adj[v].append(u)
    return idx, adj


def affected_fractions(
    hits_by_pair: dict[tuple[str, str], HitCounts],
    node_idx: dict[str, int],
    adj: list[list[int]],
    cartel_size: int,
    threshold: float,
) -> list[float]:
    nodes = list(node_idx)
    n = len(nodes)
    fractions: list[float] = []
    for cartel in itertools.combinations(range(n), cartel_size):
        cartel_set = frozenset(cartel)
        eligible = 0
        affected = 0
        for src_name, tgt_name in itertools.product(nodes, nodes):
            if src_name == tgt_name:
                continue
            s = node_idx[src_name]
            t = node_idx[tgt_name]
            if not pair_eligible_for_cartel(s, t, cartel_set, adj):
                continue
            eligible += 1
            exposure = cartel_exposure(cartel, hits_by_pair[(src_name, tgt_name)])
            if exposure > threshold:
                affected += 1
        if eligible == 0:
            continue
        fractions.append(affected / eligible)
    return fractions


def summarize(fractions: list[float]) -> tuple[float, float, float]:
    if not fractions:
        return 0.0, 0.0, 0.0
    arr = np.asarray(fractions)
    return float(np.median(arr)), float(np.mean(arr)), float(np.max(arr))


def format_pct(x: float) -> str:
    if x == 0.0:
        return "0.00\\%"
    if x < 0.01:
        return f"{x:.2f}\\%"
    return f"{x:.2f}\\%"


def print_latex_table(rows: dict[float, dict[int, tuple[float, float, float]]]) -> None:
    print("\nLaTeX rows (median / average / maximum):")
    for chi in THRESHOLDS:
        m2, a2, x2 = rows[chi][2]
        m3, a3, x3 = rows[chi][3]
        print(
            f"{int(chi * 100)}\\%  & {format_pct(100 * m2)} & {format_pct(100 * a2)} & "
            f"{format_pct(100 * x2)} & {format_pct(100 * m3)} & {format_pct(100 * a3)} & "
            f"{format_pct(100 * x3)} \\\\"
        )


def main() -> None:
    subprocess.run(["make", "-C", str(ROOT / "cpp"), "exposure"], check=True)

    graph_nodes = tuple(sorted(GEANT))
    hits_by_pair = collect_all_hits(graph_nodes, DEFAULT_RUNS)
    cpp_nodes = next(iter(hits_by_pair.values())).nodes
    if set(cpp_nodes) != set(graph_nodes):
        raise RuntimeError(f"C++ node set {set(cpp_nodes)} != GEANT {set(graph_nodes)}")
    node_idx, adj = build_index_maps(cpp_nodes)
    nodes = list(cpp_nodes)

    out_dir = ROOT / "data"
    out_dir.mkdir(exist_ok=True)
    serializable = {
        f"{s}->{t}": {
            "runs": h.runs,
            "nodes": h.nodes,
            "single": h.single.tolist(),
            "pair": h.pair.tolist(),
            "triple": {f"{a},{b},{c}": v for (a, b, c), v in h.triple.items()},
        }
        for (s, t), h in hits_by_pair.items()
    }
    with open(out_dir / "safepairs-hits.json", "w", encoding="utf-8") as f:
        json.dump(serializable, f)

    rows: dict[float, dict[int, tuple[float, float, float]]] = {}
    for cartel_size in CARTEL_SIZES:
        for threshold in tqdm.tqdm(
            THRESHOLDS,
            desc=f"cartel size {cartel_size}",
        ):
            fractions = affected_fractions(
                hits_by_pair, node_idx, adj, cartel_size, threshold
            )
            rows.setdefault(threshold, {})[cartel_size] = summarize(fractions)

    table = {
        str(chi): {
            str(m): {"median": med, "average": avg, "maximum": mx}
            for m, (med, avg, mx) in per_size.items()
        }
        for chi, per_size in rows.items()
    }
    with open(out_dir / "safepairs-table.json", "w", encoding="utf-8") as f:
        json.dump(table, f, indent=2)

    print("\nTable (fractions of eligible ordered pairs affected):")
    header = (
        f"{'chi':>5}  "
        f"{'m=2 med':>10} {'m=2 avg':>10} {'m=2 max':>10}  "
        f"{'m=3 med':>10} {'m=3 avg':>10} {'m=3 max':>10}"
    )
    print(header)
    print("-" * len(header))
    for chi in THRESHOLDS:
        m2, a2, x2 = rows[chi][2]
        m3, a3, x3 = rows[chi][3]
        print(
            f"{int(chi * 100):>4}%  "
            f"{100 * m2:10.2f}% {100 * a2:10.2f}% {100 * x2:10.2f}%  "
            f"{100 * m3:10.2f}% {100 * a3:10.2f}% {100 * x3:10.2f}%"
        )
    print_latex_table(rows)


if __name__ == "__main__":
    main()
