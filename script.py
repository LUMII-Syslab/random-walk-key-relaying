from helpers.compute import compute_hop_stats, HopStats
# from helpers.utils import read_edge_list_csv, graphs_dir
from helpers.utils import synthetic_graph_snapshot
import networkx as nx
from statistics import median, mean

# g = read_edge_list_csv(graphs_dir / "generated" / "edges.csv")
g = synthetic_graph_snapshot(99)
# s,t="MAR","TIR"
# s,t="MIL","COP"

# for var in ["R", "NB", "LRV", "HS"]:
#     hop_stats = compute_hop_stats(HopStats.HopSimParams(
#         g=g,
#         src=s,
#         tgt=t,
#         var=var,
#         no_of_runs=1000,
#     ))
#     hop_stats.print()

for walk_variant in ["R", "NB", "LRV", "HS"]:
    max_exposure, max_e_src, max_e_tgt, max_e_relay = 0.0, "", "", ""
    exposure_sum, pair_count = 0.0, 0
    for (i, s) in enumerate(g.nodes()):
        print(f"processing {i+1}/{len(g.nodes())} ({s})...", end="")
        for t in g.nodes():
            if s == t: continue
            if nx.node_connectivity(g, s, t) == 1: continue
            hop_stats = compute_hop_stats(HopStats.HopSimParams(
                g=g,
                src=s,
                tgt=t,
                var=walk_variant,
                no_of_runs=1000,
            ))
            if hop_stats.exposure > max_exposure :
                max_exposure = hop_stats.exposure
                max_e_src = s
                max_e_tgt = t
                max_e_relay = hop_stats.exposure_relay
            exposure_sum += hop_stats.exposure
            pair_count += 1
        print("\r", end="")
    print(f"{walk_variant}: max_exposure={max_exposure:.3f} s={max_e_src} t={max_e_tgt} v={max_e_relay}")
    print(f"{walk_variant}: avg_exposure={exposure_sum/pair_count:.3f} over {pair_count} pairs")
