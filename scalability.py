"""Mean hop-count scaling on incremental hexagon-graph snapshots.

Uses ``graphs.hexagon.hexagon_graph_snapshot`` to obtain growing prefixes of
the CC-spiral hexagonal grid (see ``figs/hexagon.tikz`` in the paper repo).
"""
from __future__ import annotations

import argparse
from collections import deque

from graphs.hexagon import hexagon_graph_snapshot


def shortest_hops(adj: dict[int, list[int]], src: int, tgt: int) -> int | None:
    if src == tgt:
        return 0
    prev: dict[int, int | None] = {src: None}
    q: deque[int] = deque([src])
    while q:
        u = q.popleft()
        if u == tgt:
            break
        for v in adj[u]:
            if v in prev:
                continue
            prev[v] = u
            q.append(v)
    if tgt not in prev:
        return None
    hops = 0
    cur: int | None = tgt
    while cur is not None and cur != src:
        hops += 1
        cur = prev[cur]
    return hops


def mean_hop_count(adj: dict[int, list[int]]) -> float:
    nodes = sorted(adj)
    total = 0
    pairs = 0
    for s in nodes:
        for t in nodes:
            if s == t:
                continue
            hops = shortest_hops(adj, s, t)
            if hops is None:
                raise RuntimeError(f"no path between {s} and {t}")
            total += hops
            pairs += 1
    return total / pairs


def default_snapshots() -> list[int]:
    return [6, 10, 13, 16, 19, 22, 24, 28, 31, 33, 37, 40, 43, 48, 54, 58, 65, 72, 79, 86, 96]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--snapshots",
        type=int,
        nargs="+",
        default=default_snapshots(),
        help="vertex-count prefixes to evaluate (default: CC-spiral breakpoints)",
    )
    args = parser.parse_args()

    print("nodes\tedges\tavg_degree\tmean_hops")
    for nodes in args.snapshots:
        adj = hexagon_graph_snapshot(nodes)
        edge_count = sum(len(nbrs) for nbrs in adj.values()) // 2
        active = len(adj)
        avg_deg = sum(len(nbrs) for nbrs in adj.values()) / active
        mean_hops = mean_hop_count(adj)
        print(f"{active}\t{edge_count}\t{avg_deg:.2f}\t{mean_hops:.3f}")


if __name__ == "__main__":
    main()
