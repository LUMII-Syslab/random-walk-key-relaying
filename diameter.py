#!/usr/bin/env python3
"""
Compute graph diameter(s) for the 3 bundled topologies using networkx.

No CLI args; run:
  python3 diameter.py

Reads:
  graphs/{geant,nsfnet,secoqc}/{nodes.csv,edges.csv}

Writes:
  data/diameter.csv

Notes:
- Diameter is computed in *hop count* (unweighted shortest path length).
- If a graph is disconnected, we compute the maximum diameter over connected components
  (i.e., the diameter of the graph's largest-distance component), and record connected=False.
"""

from __future__ import annotations

import csv
import os
from collections import deque
from typing import Dict, Iterable, List, Set, Tuple

try:
    import networkx as nx  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    nx = None  # type: ignore


def load_nodes_edges(nodes_csv: str, edges_csv: str) -> Tuple[List[str], List[Tuple[str, str]]]:
    nodes: List[str] = []
    with open(nodes_csv, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            node_id = row.get("Id") or row.get("ID") or row.get("id")
            if node_id:
                nodes.append(node_id)

    edges: List[Tuple[str, str]] = []
    with open(edges_csv, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            u, v = row["Source"], row["Target"]
            if u == v:
                continue
            edges.append((u, v))
    return nodes, edges


def _build_adj(nodes: Iterable[str], edges: Iterable[Tuple[str, str]]) -> Dict[str, Set[str]]:
    adj: Dict[str, Set[str]] = {n: set() for n in nodes}
    for u, v in edges:
        adj.setdefault(u, set()).add(v)
        adj.setdefault(v, set()).add(u)
    return adj


def _components(adj: Dict[str, Set[str]]) -> List[Set[str]]:
    seen: Set[str] = set()
    comps: List[Set[str]] = []
    for s in adj.keys():
        if s in seen:
            continue
        comp: Set[str] = set()
        q: deque[str] = deque([s])
        seen.add(s)
        while q:
            v = q.popleft()
            comp.add(v)
            for nb in adj.get(v, ()):
                if nb not in seen:
                    seen.add(nb)
                    q.append(nb)
        comps.append(comp)
    return comps


def _bfs_eccentricity(adj: Dict[str, Set[str]], start: str, allowed: Set[str]) -> int:
    """Max shortest-path distance from start to any node in allowed set."""
    q: deque[str] = deque([start])
    dist: Dict[str, int] = {start: 0}
    while q:
        v = q.popleft()
        for nb in adj.get(v, ()):
            if nb not in allowed or nb in dist:
                continue
            dist[nb] = dist[v] + 1
            q.append(nb)
    # allowed is connected component, so all should be reachable
    return max(dist.values()) if dist else 0


def _diameter_exact(adj: Dict[str, Set[str]], comp: Set[str]) -> int:
    if len(comp) <= 1:
        return 0
    # Exact diameter by BFS from every node (small graphs: <= 43 nodes)
    return max(_bfs_eccentricity(adj, v, comp) for v in comp)


def diameter_hops(nodes: List[str], edges: List[Tuple[str, str]]) -> Tuple[int, bool]:
    """
    Return (diameter_in_hops, connected_flag).

    Uses networkx if available, otherwise exact BFS-based computation.
    """
    if nx is not None:
        G = nx.Graph()
        G.add_nodes_from(nodes)
        G.add_edges_from(edges)
        if G.number_of_nodes() == 0:
            return 0, True
        if nx.is_connected(G):
            return int(nx.diameter(G)), True
        dmax = max(int(nx.diameter(G.subgraph(c))) if len(c) > 1 else 0 for c in nx.connected_components(G))
        return dmax, False

    # Fallback without networkx
    adj = _build_adj(nodes, edges)
    comps = _components(adj)
    connected = len(comps) == 1
    dmax = max(_diameter_exact(adj, c) for c in comps) if comps else 0
    return dmax, connected


def main() -> None:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    graphs = [
        ("geant", f"{base_dir}/graphs/geant/nodes.csv", f"{base_dir}/graphs/geant/edges.csv"),
        ("nsfnet", f"{base_dir}/graphs/nsfnet/nodes.csv", f"{base_dir}/graphs/nsfnet/edges.csv"),
        ("secoqc", f"{base_dir}/graphs/secoqc/nodes.csv", f"{base_dir}/graphs/secoqc/edges.csv"),
    ]

    out_dir = f"{base_dir}/data"
    os.makedirs(out_dir, exist_ok=True)
    out_csv = f"{out_dir}/diameter.csv"

    rows: List[Dict[str, object]] = []
    for name, nodes_csv, edges_csv in graphs:
        nodes, edges = load_nodes_edges(nodes_csv, edges_csv)
        d, connected = diameter_hops(nodes, edges)
        rows.append(
            {
                "graph": name,
                "nodes": len(set(nodes) | {u for e in edges for u in e}),
                "edges": len({tuple(sorted(e)) for e in edges}),
                "connected": connected,
                "diameter_hops": d,
            }
        )

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["graph", "nodes", "edges", "connected", "diameter_hops"])
        w.writeheader()
        for row in rows:
            w.writerow(row)

    print(f"Wrote: {out_csv}")
    for row in rows:
        print(
            f"  {row['graph']}: diameter_hops={row['diameter_hops']} "
            f"(nodes={row['nodes']}, edges={row['edges']}, connected={row['connected']})"
        )


if __name__ == "__main__":
    main()

