#!/usr/bin/env python3
"""
Approximate longest simple s->t paths for all node pairs in the 3 bundled graphs.

This script is intentionally "batteries-included": it does NOT take CLI args.
Run it as:

  python3 longest.py

It will read graph CSVs from:
  graphs/{geant,nsfnet,secoqc}/{nodes.csv,edges.csv}

and write results to:
  data/{geant,nsfnet,secoqc}/longest.csv

The computed value is an *approximation* of the longest simple path length
(in edges) between each unordered node pair (source < target order as in mflow.py).

Tuning (via environment variables):
  - LONGEST_PAIR_TIME_S : per-pair time budget (default: 0.1)
  - LONGEST_BRANCH_K    : max neighbors explored per node (default: 4)
  - LONGEST_SEED        : base RNG seed (default: 1)
"""

from __future__ import annotations

import csv
import itertools
import os
import random
import time
from collections import deque
from typing import Dict, Hashable, List, Set, Tuple


Node = Hashable
Adj = Dict[Node, Set[Node]]


def load_graph(nodes_csv: str, edges_csv: str) -> Tuple[List[str], Adj]:
    nodes: List[str] = []
    with open(nodes_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            node_id = row.get("Id") or row.get("ID") or row.get("id")
            if node_id:
                nodes.append(node_id)

    adj: Adj = {n: set() for n in nodes}
    with open(edges_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            u, v = row["Source"], row["Target"]
            if u not in adj:
                adj[u] = set()
                nodes.append(u)
            if v not in adj:
                adj[v] = set()
                nodes.append(v)
            if u == v:
                continue
            adj[u].add(v)
            adj[v].add(u)

    # de-duplicate nodes list while preserving order
    seen: Set[str] = set()
    nodes2: List[str] = []
    for n in nodes:
        if n not in seen:
            seen.add(n)
            nodes2.append(n)
    return nodes2, adj


def _can_reach_target(adj: Adj, start: str, target: str, used: Set[str]) -> bool:
    """BFS reachability in the induced subgraph of (unused nodes) U {target}."""
    if start == target:
        return True
    q: deque[str] = deque([start])
    seen: Set[str] = {start}
    while q:
        v = q.popleft()
        for nb in adj.get(v, ()):
            if nb != target and nb in used:
                continue
            if nb in seen:
                continue
            if nb == target:
                return True
            seen.add(nb)
            q.append(nb)
    return False


def _shortest_path_nodes(adj: Adj, source: str, target: str) -> List[str]:
    """Unweighted shortest path (BFS). Returns [] if unreachable."""
    if source == target:
        return [source]
    q: deque[str] = deque([source])
    parent: Dict[str, str | None] = {source: None}
    while q:
        v = q.popleft()
        for nb in adj.get(v, ()):
            if nb in parent:
                continue
            parent[nb] = v
            if nb == target:
                # reconstruct
                out = [target]
                cur = v
                while cur is not None:
                    out.append(cur)
                    cur = parent[cur]
                out.reverse()
                return out
            q.append(nb)
    return []


def approximate_longest_simple_st_path(
    adj: Adj,
    source: str,
    target: str,
    *,
    time_limit_s: float,
    branch_k: int,
    rng: random.Random,
) -> List[str]:
    """
    Heuristic search for a long simple path from source to target.
    Returns a node list (path), empty if none found.
    """
    if source == target:
        return [source]
    if source not in adj or target not in adj:
        return []

    n_total = len(adj)
    # Always have a baseline path so we never output "-1" just because
    # the heuristic search didn't reach the target within the time budget.
    best: List[str] = _shortest_path_nodes(adj, source, target)
    if not best:
        return []

    t0 = time.perf_counter()

    used: Set[str] = {source}
    path: List[str] = [source]

    def candidates(v: str) -> List[str]:
        c = [nb for nb in adj.get(v, ()) if nb not in used]
        # diversify, but prefer "constrained" vertices early (helps avoid dead-ends)
        rng.shuffle(c)
        c.sort(key=lambda x: len(adj.get(x, ())))
        if branch_k > 0:
            return c[:branch_k]
        return c

    # Stack frames: (node, candidate_list, next_index)
    stack: List[Tuple[str, List[str], int]] = [(source, candidates(source), 0)]

    steps = 0
    while stack and (time.perf_counter() - t0) < time_limit_s:
        v, cands, idx = stack[-1]

        # optimistic bound: even if we visit all remaining unused nodes, can we beat best?
        if len(path) + (n_total - len(used)) <= len(best):
            # backtrack
            if v == source:
                break
            stack.pop()
            used.remove(v)
            path.pop()
            continue

        # occasionally do reachability pruning (BFS is non-trivial cost)
        steps += 1
        if steps % 64 == 0 and not _can_reach_target(adj, v, target, used):
            if v == source:
                break
            stack.pop()
            used.remove(v)
            path.pop()
            continue

        if v == target:
            if len(path) > len(best):
                best = path.copy()
            # can't extend beyond target (endpoints fixed) -> backtrack
            if v == source:
                break
            stack.pop()
            used.remove(v)
            path.pop()
            continue

        if idx >= len(cands):
            # exhausted neighbors -> backtrack
            if v == source:
                break
            stack.pop()
            used.remove(v)
            path.pop()
            continue

        nb = cands[idx]
        stack[-1] = (v, cands, idx + 1)
        if nb in used:
            continue

        used.add(nb)
        path.append(nb)
        stack.append((nb, candidates(nb), 0))

    return best


def main() -> None:
    base_dir = os.path.dirname(os.path.abspath(__file__))

    time_per_pair_s = float(os.getenv("LONGEST_PAIR_TIME_S", "0.1"))
    branch_k = int(os.getenv("LONGEST_BRANCH_K", "4"))
    base_seed = int(os.getenv("LONGEST_SEED", "1"))

    graphs = [
        ("geant", f"{base_dir}/graphs/geant/nodes.csv", f"{base_dir}/graphs/geant/edges.csv"),
        ("nsfnet", f"{base_dir}/graphs/nsfnet/nodes.csv", f"{base_dir}/graphs/nsfnet/edges.csv"),
        ("secoqc", f"{base_dir}/graphs/secoqc/nodes.csv", f"{base_dir}/graphs/secoqc/edges.csv"),
    ]

    for name, nodes_csv, edges_csv in graphs:
        nodes, adj = load_graph(nodes_csv, edges_csv)
        out_dir = f"{base_dir}/data/{name}"
        os.makedirs(out_dir, exist_ok=True)
        out_csv = f"{out_dir}/longest.csv"

        print(f"\n{name.upper()}")
        print("-" * 40)
        print(f"  Nodes: {len(nodes)}, Edges: {sum(len(v) for v in adj.values()) // 2}")
        print(f"  Per-pair time budget: {time_per_pair_s}s, branch_k={branch_k}, seed={base_seed}")
        print(f"  Writing: {out_csv}")

        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["source", "target", "longest_simple_approx"],
            )
            w.writeheader()

            # same unordered-pair iteration style as mflow.py
            for source, target in itertools.combinations(nodes, 2):
                # make per-pair RNG stable but distinct
                pair_seed = (hash((name, source, target, base_seed)) & 0xFFFFFFFF) ^ base_seed
                rng = random.Random(pair_seed)
                best_path = approximate_longest_simple_st_path(
                    adj,
                    source,
                    target,
                    time_limit_s=time_per_pair_s,
                    branch_k=branch_k,
                    rng=rng,
                )
                longest_len = (len(best_path) - 1) if best_path else -1
                w.writerow(
                    {
                        "source": source,
                        "target": target,
                        "longest_simple_approx": longest_len,
                    }
                )


if __name__ == "__main__":
    main()
