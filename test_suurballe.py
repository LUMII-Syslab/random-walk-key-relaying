"""Integration tests for Suurballe node-disjoint path finding.

For every ordered source-target pair in the GEANT topology, NetworkX supplies
the local vertex connectivity ``k``. Suurballe is run with that ``k`` and the
returned paths are checked to:

  - have the correct count and endpoints,
  - use only edges present in the adjacency list,
  - be internally node-disjoint (terminals ``s`` and ``t`` may repeat).
"""
from __future__ import annotations

import networkx as nx
import pytest

import graphs
from suurballe import suurballe


def assert_path_connected(adj_list: dict[int, list[int]], path: list[int]) -> None:
    for u, v in zip(path, path[1:]):
        assert v in adj_list[u], f"edge ({u}, {v}) missing from adjacency list"


def assert_paths_node_disjoint(paths: list[list[int]], s: int, t: int) -> None:
    for i, path_a in enumerate(paths):
        internal_a = set(path_a[1:-1])
        for path_b in paths[i + 1 :]:
            internal_b = set(path_b[1:-1])
            assert internal_a.isdisjoint(internal_b)

@pytest.fixture(scope="module")
def geant_str_adj_list() -> dict[str, list[str]]:
    return graphs.get_graph_str_adj_list("GEANT")

def test_geant_all_pairs(
    geant_str_adj_list: dict[str, list[str]],
) -> None:
    geant_int_adj_list = graphs.str_adj_list_to_int_adj_list(geant_str_adj_list)
    geant_nx = graphs.str_adj_list_to_nx_graph(geant_str_adj_list)
    n = len(geant_int_adj_list)
    for s in range(n):
        for t in range(n):
            if s == t:
                continue

            s_name = graphs.node_idx_to_name(s, geant_str_adj_list)
            t_name = graphs.node_idx_to_name(t, geant_str_adj_list)
            k = nx.node_connectivity(geant_nx, s_name, t_name)
            assert k > 0, f"GEANT should be connected; got k=0 for ({s}, {t})"

            paths = suurballe(geant_int_adj_list, s, t, k)
            assert len(paths) == k

            for path in paths:
                assert path[0] == s and path[-1] == t
                assert_path_connected(geant_int_adj_list, path)

            assert_paths_node_disjoint(paths, s, t)
