from graphs import get_graph_int_adj_list, get_graph_nx_graph, get_graph_str_adj_list, node_idx_to_name
import networkx as nx
from suurballe import suurballe

geant = get_graph_int_adj_list("GEANT")
nodes = list(geant.keys())
geant_str_adj_list = get_graph_str_adj_list("GEANT")
geant_nx = get_graph_nx_graph("GEANT")

edge_counter: dict[tuple[int, int], int] = {}

for s in nodes:
    for t in nodes:
        if s == t: continue
        # print(f"Computing paths for ({s}, {t})")
        s_name = node_idx_to_name(s, geant_str_adj_list)
        t_name = node_idx_to_name(t, geant_str_adj_list)
        k = nx.node_connectivity(geant_nx, s_name, t_name)
        paths = suurballe(geant, s, t, k)
        for path in paths:
            for u, v in zip(path, path[1:]):
                if (u, v) not in edge_counter:
                    edge_counter[(u, v)] = 0
                edge_counter[(u, v)] += 128

entries: list[tuple[int, int, int]] = []
for (u, v), count in edge_counter.items():
    entries.append((u, v, count))

entries.sort(key=lambda x: x[2], reverse=True)

for u, v, count in entries:
    print(f"({u}, {v}): {count}")