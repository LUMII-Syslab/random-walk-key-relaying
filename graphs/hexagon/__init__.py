"""Hardcoded hexagonal-grid graph from ``gengraph.py`` / ``edges.csv``."""
from __future__ import annotations

import sys

# 1-indexed directed edges from graphs/hexagon/edges.csv
HEXAGON_EDGES: tuple[tuple[int, int], ...] = (
    (2, 1), (3, 2), (4, 3), (5, 4), (6, 5), (6, 1), (7, 3), (8, 7), (9, 8), (10, 9),
    (10, 4), (12, 11), (13, 12), (13, 7), (11, 2), (15, 14), (15, 11), (16, 1), (16, 14), (17, 16),
    (18, 6), (19, 18), (19, 17), (20, 5), (21, 20), (22, 21), (22, 18), (23, 10), (24, 23), (24, 20),
    (25, 8), (26, 25), (27, 26), (28, 27), (28, 9), (29, 13), (30, 29), (30, 25), (32, 31), (33, 32),
    (33, 29), (31, 12), (35, 34), (35, 31), (34, 15), (37, 36), (37, 34), (38, 14), (38, 36), (39, 38),
    (40, 17), (40, 39), (41, 40), (42, 19), (43, 42), (43, 41), (44, 22), (45, 44), (45, 42), (46, 21),
    (47, 46), (48, 47), (48, 44), (49, 24), (50, 49), (50, 46), (51, 23), (52, 51), (53, 52), (53, 49),
    (54, 28), (54, 51), (55, 26), (56, 55), (57, 56), (58, 57), (58, 27), (59, 30), (60, 59), (60, 55),
    (61, 33), (62, 61), (62, 59), (64, 63), (65, 64), (65, 61), (63, 32), (67, 66), (67, 63), (66, 35),
    (69, 68), (69, 66), (68, 37), (71, 70), (71, 68), (72, 36), (72, 70), (73, 72), (74, 39), (74, 73),
    (75, 74), (76, 41), (76, 75), (77, 76), (78, 43), (79, 78), (79, 77), (80, 45), (81, 80), (81, 78),
    (82, 48), (83, 82), (83, 80), (84, 47), (85, 84), (86, 85), (86, 82), (87, 50), (88, 87), (88, 84),
    (89, 53), (90, 89), (90, 87), (91, 52), (92, 91), (93, 92), (93, 89), (94, 54), (95, 94), (95, 91),
    (96, 58), (96, 94),
)

HEXAGON_VERTEX_COUNT = 96
HEXAGON_HEX_COUNT = 37


def hexagon_graph_snapshot(nodes: int) -> dict[int, list[int]]:
    """Return a prefix of the hexagonal grid on ``nodes`` vertices.

    Small hexagons are added in CC spiral order; each insertion assigns labels
    to previously unseen vertices and adds any new edges whose endpoints both
    exist. Edge endpoints are 1-indexed in ``HEXAGON_EDGES``. Edges whose
    source is greater than ``nodes`` are dropped, then isolated vertices are
    removed.
    """
    if nodes < 1 or nodes > HEXAGON_VERTEX_COUNT:
        raise ValueError(f"nodes must be between 1 and {HEXAGON_VERTEX_COUNT}")

    import networkx as nx

    di_graph = nx.DiGraph(HEXAGON_EDGES)
    for edge in list(di_graph.edges()):
        if edge[0] > nodes:
            di_graph.remove_edge(edge[0], edge[1])
    di_graph.remove_nodes_from(list(nx.isolates(di_graph)))
    g = nx.Graph(di_graph)
    return {v: list(g.neighbors(v)) for v in g.nodes()}
