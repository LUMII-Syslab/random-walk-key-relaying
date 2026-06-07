"""Count edge load from shortest-path routing over all ordered (s, t) pairs.

For each ordered pair of distinct nodes, route one unweighted shortest path
(BFS) and increment the count on each undirected edge along that path.
The bottleneck edge is the edge with the largest count.
"""
from __future__ import annotations

from collections import deque

from graphs import get_graph_int_adj_list


def shortest_path(adj: dict[int, list[int]], src: int, tgt: int) -> list[int] | None:
    if src == tgt:
        return [src]
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
    path: list[int] = []
    cur: int | None = tgt
    while cur is not None:
        path.append(cur)
        cur = prev[cur]
    path.reverse()
    return path


def edge_key(u: int, v: int) -> tuple[int, int]:
    return (u, v) if u < v else (v, u)


geant = get_graph_int_adj_list("GEANT")
nodes = list(geant.keys())

edge_counter: dict[tuple[int, int], int] = {}

for s in nodes:
    for t in nodes:
        if s == t:
            continue
        path = shortest_path(geant, s, t)
        if path is None:
            raise RuntimeError(f"No path between {s} and {t}")
        for u, v in zip(path, path[1:]):
            ek = edge_key(u, v)
            edge_counter[ek] = edge_counter.get(ek, 0) + 1

entries: list[tuple[int, int, int]] = [
    (u, v, count) for (u, v), count in edge_counter.items()
]
entries.sort(key=lambda x: x[2], reverse=True)

for u, v, count in entries:
    print(f"({u}, {v}): {count}")

if entries:
    u, v, count = entries[0]
    print(f"bottleneck: ({u}, {v}) count={count}")
