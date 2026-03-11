from helpers.compute import compute_hop_stats, HopStats
from helpers.utils import read_edge_list_csv, graphs_dir
from helpers.utils import synthetic_graph_snapshot
import networkx as nx
from statistics import median, mean
import sys

if sys.argv[1] == "generated":
    g= synthetic_graph_snapshot(99)
else:
    g = read_edge_list_csv(graphs_dir / sys.argv[1] / "edges.csv")

for walk_variant in ['R', 'NB', 'LRV', 'NC', 'HS']:
    max_exposure, max_e_src, max_e_tgt, max_e_relay = 0.0, "", "", ""
    pair_exposures = []
    pair_mean_hop_counts = []
    pair_max_hop_counts = []
    for (i, s) in enumerate(g.nodes()):
        print(f"processing {i+1}/{len(g.nodes())} ({s})...", end="",flush=True)
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
            pair_exposures.append(hop_stats.exposure)
            pair_mean_hop_counts.append(hop_stats.mean_hops)
            pair_max_hop_counts.append(hop_stats.max_hops)
        print(f"\r{' '*100}\r", end="", flush=True)
    avg_exposure = mean(pair_exposures) if pair_exposures else float('nan')
    median_exposure = median(pair_exposures) if pair_exposures else float('nan')
    print(f"graph: {sys.argv[1]}")
    print(f"{walk_variant}: max_exposure={max_exposure:.3f} s={max_e_src} t={max_e_tgt} v={max_e_relay}")
    print(f"{walk_variant}: avg_exposure={avg_exposure:.3f} median_exposure={median_exposure:.3f} over {len(pair_exposures)} pairs")
    print(f"{walk_variant}: avg_mean_hop_count={int(mean(pair_mean_hop_counts)):.0f} avg_max_hop_count={int(mean(pair_max_hop_counts)):.0f}")
