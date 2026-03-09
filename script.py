from helpers.compute import compute_hop_stats, HopStats
from helpers.utils import read_edge_list_csv, graphs_dir
import networkx as nx

g = read_edge_list_csv(graphs_dir / "geant" / "edges.csv")
s,t="MAR","TIR"
# s,t="MIL","COP"

for var in ["R", "NB", "LRV", "HS"]:
    hop_stats = compute_hop_stats(HopStats.HopSimParams(
        g=g,
        src=s,
        tgt=t,
        var=var,
        no_of_runs=1000,
    ))
    hop_stats.print()

for walk_variant in ["R", "NB", "LRV", "HS"]:
    max_hit_prob, max_hit_source, max_hit_target, max_hit_node = 0.0, "", "", ""
    for (i, s) in enumerate(g.nodes()):
        print(f"processing {i+1}/{len(g.nodes())} ({s})...", end="")
        for t in g.nodes():
            if s == t: continue
            pair = (s, t)
            if nx.node_connectivity(g, s, t) == 1: continue
            hop_stats = compute_hop_stats(HopStats.HopSimParams(
                g=g,
                src=s,
                tgt=t,
                var=walk_variant,
                no_of_runs=1000,
            ))
            if hop_stats.max_hit_prob > max_hit_prob :
                max_hit_prob = hop_stats.max_hit_prob
                max_hit_source = s
                max_hit_target = t
                max_hit_node = hop_stats.max_hit_node
        print("\r", end="")
    print(f"{walk_variant}: exposure={max_hit_prob:.3f} s={max_hit_source} t={max_hit_target} v={max_hit_node}")