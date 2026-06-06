"""Hardcoded synthetic graph from ``gengraph.py`` / ``edges.csv``."""
from __future__ import annotations

import sys

# 1-indexed directed edges from graphs/generated/edges.csv
GENERATED_EDGES: tuple[tuple[int, int], ...] = (
    (2, 1), (3, 2), (4, 1), (5, 2), (5, 4), (6, 3), (6, 5), (7, 2), (8, 4),
    (8, 7), (9, 3), (9, 8), (10, 4), (11, 1), (11, 10), (12, 6), (12, 11),
    (13, 9), (14, 13), (15, 7), (15, 14), (16, 15), (17, 16), (18, 2), (18, 17),
    (19, 6), (20, 19), (21, 17), (21, 20), (22, 4), (23, 22), (24, 16), (24, 23),
    (25, 18), (26, 25), (27, 16), (27, 26), (28, 9), (29, 28), (30, 8), (30, 29),
    (31, 4), (32, 31), (33, 5), (33, 32), (34, 15), (35, 34), (36, 1), (36, 35),
    (37, 26), (38, 37), (39, 16), (39, 38), (40, 25), (41, 26), (41, 40), (42, 27),
    (42, 41), (43, 17), (44, 43), (45, 5), (45, 44), (46, 45), (47, 46), (48, 11),
    (48, 47), (49, 34), (50, 36), (50, 49), (51, 13), (51, 50), (52, 17), (53, 52),
    (54, 33), (54, 53), (55, 2), (56, 35), (56, 55), (57, 14), (57, 56), (58, 32),
    (59, 58), (60, 53), (60, 59), (61, 58), (62, 21), (62, 61), (63, 19), (63, 62),
    (64, 23), (65, 64), (66, 29), (66, 65), (67, 16), (68, 67), (69, 18), (69, 68),
    (70, 10), (71, 45), (71, 70), (72, 60), (72, 71), (73, 44), (74, 73), (75, 18),
    (75, 74), (76, 2), (77, 9), (77, 76), (78, 1), (78, 77), (79, 27), (80, 37),
    (80, 79), (81, 25), (81, 80), (82, 8), (83, 82), (84, 66), (84, 83), (85, 22),
    (86, 24), (86, 85), (87, 82), (87, 86), (88, 81), (89, 88), (90, 40), (90, 89),
    (91, 50), (92, 36), (92, 91), (93, 51), (93, 92), (94, 7), (95, 77), (95, 94),
    (96, 76), (96, 95), (97, 6), (98, 97), (99, 5), (99, 98),
)


def synthetic_graph_snapshot(nodes: int) -> dict[int, list[int]]:
    """Return a prefix of the hardcoded generated graph on ``nodes`` vertices.

    Edge endpoints are 1-indexed in ``GENERATED_EDGES``, matching the CSV that
    was produced by ``gengraph.py``. Edges whose source is greater than ``nodes``
    are dropped, then isolated vertices are removed. Keys are the original
    integer vertex labels (typically ``1 .. nodes``).
    """
    if nodes < 1 or nodes > 99:
        raise ValueError("nodes must be between 1 and 99")
    if nodes % 3 != 0:
        print("Warning: synthetic graph snapshot may be malformed!", file=sys.stderr)

    import networkx as nx

    di_graph = nx.DiGraph(GENERATED_EDGES)
    for edge in list(di_graph.edges()):
        if edge[0] > nodes:
            di_graph.remove_edge(edge[0], edge[1])
    di_graph.remove_nodes_from(list(nx.isolates(di_graph)))
    g = nx.Graph(di_graph)
    return {v: list(g.neighbors(v)) for v in g.nodes()}
