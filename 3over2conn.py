from helpers.graphs import read_geant_graph, read_nsfnet_graph, read_secoqc_graph, synthetic_graph_snapshot
from networkx import node_connectivity
import tqdm

graph = synthetic_graph_snapshot(99)

pair_count = 0
two_conn = 0
three_conn = 0
for src in tqdm.tqdm(graph.nodes()):
    for tgt in graph.nodes():
        if src == tgt: continue
        pair_count += 1
        node_conn = node_connectivity(graph, src, tgt)
        if node_conn >= 2: two_conn += 1
        if node_conn >= 3: three_conn += 1

print(f"pair_count: {pair_count}")
# print(f"two_conn: {two_conn}")
# print(f"three_conn: {three_conn}")
print(f"two_conn_ratio: {two_conn / pair_count}")
# print(f"three_conn_ratio: {three_conn / pair_count}")
print(f"three_conn_over_two_conn_ratio: {three_conn / two_conn}")