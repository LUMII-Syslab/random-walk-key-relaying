#!/usr/bin/env python3
"""Generate the hexagonal-grid scalability topology.

Small hexagons are added in counter-clockwise spiral order (``spiral_cells``).
When a hexagon is inserted, every vertex on its boundary that is not already
present receives the next integer label; edges appear when both endpoints exist.
"""
from __future__ import annotations

import csv
import math
from collections import deque
from pathlib import Path

N = 4  # big-hex side length, measured in small hexagons
A = 1.0
ROUND = 8

DIRS = [
    (1, 0),
    (1, -1),
    (0, -1),
    (-1, 0),
    (-1, 1),
    (0, 1),
]


def spiral_cells(n: int):
    """Yield axial coordinates of hexagons in CC spiral order."""
    yield (0, 0)
    for radius in range(1, n):
        q, r = -radius, radius
        for dq, dr in DIRS:
            for _ in range(radius):
                yield (q, r)
                q += dq
                r += dr


def axial_to_xy(q: int, r: int) -> tuple[float, float]:
    x = A * 1.5 * q
    y = A * math.sqrt(3) * (r + q / 2)
    return x, y


def hex_vertices(q: int, r: int):
    cx, cy = axial_to_xy(q, r)
    for k in range(6):
        angle = math.pi / 3 * k
        yield cx + A * math.cos(angle), cy + A * math.sin(angle)


def vertex_key(x: float, y: float) -> tuple[float, float]:
    return round(x, ROUND), round(y, ROUND)


def build_hexagon_graph(n: int = N) -> tuple[list[tuple[int, int]], int, int]:
    """Return directed insertion-order edges, vertex count, hexagon count."""
    vertex_id: dict[tuple[float, float], int] = {}
    directed_edges: list[tuple[int, int]] = []
    seen_undirected: set[tuple[int, int]] = set()
    hex_count = 0

    for q, r in spiral_cells(n):
        hex_count += 1
        hex_v: list[int] = []
        for x, y in hex_vertices(q, r):
            key = vertex_key(x, y)
            if key not in vertex_id:
                vertex_id[key] = len(vertex_id) + 1
            hex_v.append(vertex_id[key])

        for i in range(6):
            u, v = hex_v[i], hex_v[(i + 1) % 6]
            lo, hi = min(u, v), max(u, v)
            if (lo, hi) in seen_undirected:
                continue
            seen_undirected.add((lo, hi))
            directed_edges.append((hi, lo))

    return directed_edges, len(vertex_id), hex_count


def hexagon_vertex_milestones(n: int = N) -> list[int]:
    """Vertex count after each hexagon in CC spiral order."""
    vertex_id: dict[tuple[float, float], int] = {}
    milestones: list[int] = []

    for q, r in spiral_cells(n):
        max_id = 0
        for x, y in hex_vertices(q, r):
            key = vertex_key(x, y)
            if key not in vertex_id:
                vertex_id[key] = len(vertex_id) + 1
            max_id = max(max_id, vertex_id[key])
        milestones.append(max_id)

    return milestones


def snapshot_directed_edges(
    nodes: int, edges: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    return [(src, tgt) for src, tgt in edges if src <= nodes]


def write_edges_csv(path: Path, edges: list[tuple[int, int]]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Source", "Target"])
        for src, tgt in edges:
            writer.writerow([src, tgt])


def snapshot_adj(nodes: int, edges: list[tuple[int, int]]) -> dict[int, list[int]]:
    adj: dict[int, set[int]] = {}
    for src, tgt in edges:
        if src > nodes:
            continue
        adj.setdefault(src, set()).add(tgt)
        adj.setdefault(tgt, set()).add(src)

    active = {v for v in adj if adj[v]}
    return {v: sorted(adj[v]) for v in sorted(active)}


def is_connected(adj: dict[int, list[int]]) -> bool:
    if not adj:
        return True
    start = next(iter(adj))
    seen = {start}
    q: deque[int] = deque([start])
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v in seen:
                continue
            seen.add(v)
            q.append(v)
    return len(seen) == len(adj)


def main() -> None:
    edges, vertex_count, hex_count = build_hexagon_graph(N)
    out_dir = Path(__file__).resolve().parent
    edges_csv = out_dir / "edges.csv"

    with edges_csv.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Source", "Target"])
        for src, tgt in edges:
            writer.writerow([src, tgt])

    avg_degree = 2 * len(edges) / vertex_count
    print(f"N = {N}")
    print(f"small hexagons = {hex_count}")
    print(f"vertices = {vertex_count}")
    print(f"edges = {len(edges)}")
    print(f"average degree = {avg_degree:.2f}")
    print(f"wrote {edges_csv}")

    breakpoints = [6, 10, 13, 16, 24, 37, 54, 96]
    for nodes in breakpoints:
        if nodes > vertex_count:
            continue
        adj = snapshot_adj(nodes, edges)
        if not is_connected(adj):
            raise RuntimeError(f"snapshot on {nodes} vertices is disconnected")
        deg = sum(len(nbrs) for nbrs in adj.values()) / len(adj)
        print(f"snapshot n={nodes}: active={len(adj)} avg_deg={deg:.2f}")


if __name__ == "__main__":
    main()
