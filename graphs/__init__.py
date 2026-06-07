"""Hardcoded topology adjacency lists and conversion helpers.

Named graphs (NSFNET, GEANT) are stored in memory so callers can pass a graph
name alone, e.g. as a joblib cache key argument, without serializing the
full adjacency list (faster key hashing) and without rereading edge lists from
CSV on disk.

The synthetic / generated graph lives in ``graphs.generated``; its vertices
are integers and is built from a hardcoded edge list with the same snapshot
logic as the old CSV-based loader.
"""
from __future__ import annotations

from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    import networkx as nx

def get_graph_str_adj_list(graph_name: Literal["NSFNET", "GEANT"]) -> dict[str, list[str]]:
    return {
        "NSFNET": NSFNET,
        "GEANT": GEANT,
    }[graph_name]

def str_adj_list_to_nx_graph(adj_list: dict[str, list[str]]) -> nx.Graph:
    import networkx as nx

    g = nx.Graph()
    for u, neighbors in adj_list.items():
        for v in neighbors:
            g.add_edge(u, v)
    return g

def get_graph_nx_graph(graph_name: Literal["NSFNET", "GEANT"]) -> nx.Graph:
    return str_adj_list_to_nx_graph(get_graph_str_adj_list(graph_name))

# Sometimes conversion to int adj list grants better performance
def str_adj_list_to_int_adj_list(adj_list: dict[str, list[str]]) -> dict[int, list[int]]:
    node_universe = sorted(set(adj_list.keys()))
    node_idx = {node: idx for idx, node in enumerate(node_universe)}
    int_adj_list = {node_idx[node]: [node_idx[n] for n in adj_list[node]] for node in adj_list}
    return int_adj_list

def get_graph_int_adj_list(graph_name: Literal["NSFNET", "GEANT"]) -> dict[int, list[int]]:
    return str_adj_list_to_int_adj_list(get_graph_str_adj_list(graph_name))

# If we have converted to int adj list, and wish to retrieve the name of a node
def node_idx_to_name(idx: int, str_adj_list: dict[str, list[str]]) -> str:
    return sorted(str_adj_list.keys())[idx]

# Warning! We should prefer converting from str adj list to nx graph if
# applicable because otherwise we lose the names without gain in performance
# as networkx calls are likely not bottlenecked by string operations.
# This function is here just for rare scenario when working with the
# generated graphs in which nodes do not have names.
def int_adj_dict_to_nx(adj_list: dict[int, list[int]]) -> nx.Graph:
    import networkx as nx

    g = nx.Graph()
    g.add_nodes_from(adj_list)
    for u, neighbors in adj_list.items():
        for v in neighbors:
            g.add_edge(u, v)
    return g

NSFNET = {
    "SEA": ["PAO", "SAN", "CMI"],
    "PAO": ["SEA", "SLC", "SAN"],
    "SAN": ["SEA", "PAO", "HOU"],
    "CMI": ["SEA", "PIT", "LNK"],
    "SLC": ["PAO", "BOU", "ARB"],
    "HOU": ["SAN", "ATL", "CPK", "BOU"],
    "ATL": ["HOU", "PIT"],
    "CPK": ["HOU", "ITH", "PRI"],
    "BOU": ["HOU", "LNK", "SLC"],
    "PIT": ["ATL", "PRI", "ITH", "CMI"],
    "PRI": ["PIT", "ARB", "CPK"],
    "ITH": ["PIT", "ARB", "CPK"],
    "LNK": ["CMI", "BOU"],
    "ARB": ["SLC", "PRI", "ITH"],
}

GEANT = {
    "PRA": ["VIE", "POZ", "FRA"],
    "VIE": ["PRA", "BRA", "MIL"],
    "BRA": ["VIE", "BUD"],
    "HEL": ["STO", "TAR", "COP"],
    "STO": ["HEL", "OSL"],
    "KAU": ["RIG", "POZ"],
    "RIG": ["KAU", "TAR"],
    "GEN": ["MAR", "PAR", "MIL", "FRA"],
    "MAR": ["GEN", "MAD", "MIL"],
    "BIL": ["PAR", "POR", "MAD"],
    "PAR": ["BIL", "GEN", "LON", "BRU", "COR"],
    "LJU": ["ZAG", "MIL"],
    "ZAG": ["LJU", "BEL", "POD", "BUD"],
    "BER": ["HAM", "POZ", "COP"],
    "HAM": ["BER", "COP", "AMS"],
    "BUC": ["SOF", "BUD"],
    "SOF": ["BUC", "BEL", "IST", "TIR", "THE", "SKO"],
    "TAR": ["HEL", "RIG"],
    "LIS": ["POR", "SIN", "MAD"],
    "POR": ["LIS", "BIL"],
    "COP": ["HAM", "HEL", "BER", "OSL"],
    "LON": ["PAR", "DUB", "AMS"],
    "BEL": ["SOF", "ZAG", "SKO"],
    "IST": ["SOF", "THE"],
    "DUB": ["LON", "COR"],
    "SIN": ["LIS"],
    "MIL": ["GEN", "VIE", "TIR", "MAR", "LJU"],
    "BRU": ["LUX", "PAR", "AMS"],
    "LUX": ["BRU", "FRA"],
    "TIR": ["SOF", "MIL"],
    "POZ": ["BER", "KIE", "PRA", "KAU"],
    "THE": ["SOF", "ATH", "IST"],
    "AMS": ["BRU", "FRA", "HAM", "LON"],
    "ATH": ["THE", "NIC"],
    "COR": ["DUB", "PAR"],
    "FRA": ["GEN", "AMS", "LUX", "PRA"],
    "MAD": ["MAR", "LIS", "BIL"],
    "BUD": ["BUC", "BRA", "ZAG"],
    "POD": ["ZAG"],
    "SKO": ["BEL", "SOF"],
    "OSL": ["STO", "COP"],
    "KIE": ["POZ"],
    "NIC": ["ATH"],
}
