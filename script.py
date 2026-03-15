from helpers.compute import compute_hop_stats, HopStats
from helpers.utils import read_edge_list_csv, graphs_dir
from helpers.utils import synthetic_graph_snapshot
import networkx as nx
from statistics import median, mean
from tqdm import tqdm
from scipy.stats import binom

GRAPH_SPECS = [
    ("nsfnet", "NSFNet"),
    ("geant", "GÉANT"),
    ("generated", "Generated"),
]

result_log = open("result.log", "a")

def prob(g, N, chi):
    a = 1.0 - chi
    # P[X >= g] for X ~ Binomial(N, a)
    return binom.sf(g - 1, N, a)

def find_g(N, chi, threshold):
    for g in range(N, -1, -1):
        if prob(g, N, chi) >= threshold: return g
    return -1

for graph_id, graph_label in GRAPH_SPECS[2:]:
    g = read_edge_list_csv(graphs_dir / graph_id / "edges.csv")
    for walk_variant in ['NB', 'LRV', 'NC', 'HS']:
        biconnected_pairs = []
        for src in tqdm(g.nodes(), desc=f"Finding biconnected pairs for {graph_label}"):
            for tgt in g.nodes():
                if src == tgt: continue
                if nx.node_connectivity(g, src, tgt) == 1: continue
                biconnected_pairs.append((src, tgt))
        assm_efficiencies_dont_erase_loops = []
        true_efficiencies_dont_erase_loops = []
        assm_efficiencies_erase_loops = []
        true_efficiencies_erase_loops = []
        assm_rho_dont_erase_loops = []
        true_rho_dont_erase_loops = []
        assm_rho_erase_loops = []
        true_rho_erase_loops = []

        for src, tgt in tqdm(biconnected_pairs, desc=f"Computing hop stats for {graph_label}"):
            hop_stats_no_erase_loops = compute_hop_stats(HopStats.HopSimParams(
                g=g,
                src=src,
                tgt=tgt,
                var=walk_variant,
                no_of_runs=1000,
                erase_loops=False,
            ))
            hop_stats_erase_loops = compute_hop_stats(HopStats.HopSimParams(
                g=g,
                src=src,
                tgt=tgt,
                var=walk_variant,
                no_of_runs=1000,
                erase_loops=True,
            ))

            mean_hops = hop_stats_no_erase_loops.mean_hops
            exposure = hop_stats_no_erase_loops.exposure
            FRAGMENTS, ALPHA = 1024, 0.9999
            good_fragments = find_g(FRAGMENTS, exposure, ALPHA)
            assert good_fragments > 0
            assert good_fragments <= FRAGMENTS
            assm_efficiency = (27/FRAGMENTS) / mean_hops
            true_efficiency = (good_fragments/FRAGMENTS) / mean_hops
            assm_efficiencies_dont_erase_loops.append(assm_efficiency)
            true_efficiencies_dont_erase_loops.append(true_efficiency)
            shortest_path = nx.shortest_path_length(g, src, tgt)
            assm_rho_dont_erase_loops.append(assm_efficiency * shortest_path)
            true_rho_dont_erase_loops.append(true_efficiency * shortest_path)

            mean_hops = hop_stats_erase_loops.mean_hops
            exposure = hop_stats_no_erase_loops.exposure # we still take exposure before erasing the loops
            good_fragments = find_g(FRAGMENTS, exposure, ALPHA)
            assert good_fragments > 0
            assert good_fragments <= FRAGMENTS
            assm_efficiency = (27/FRAGMENTS) / mean_hops
            true_efficiency = (good_fragments/FRAGMENTS) / mean_hops
            assm_efficiencies_erase_loops.append(assm_efficiency)
            true_efficiencies_erase_loops.append(true_efficiency)
            assm_rho_erase_loops.append(assm_efficiency * shortest_path)
            true_rho_erase_loops.append(true_efficiency * shortest_path)
        log_entry = f"{graph_label} {walk_variant} assm_eff_dont_erase_loops={mean(assm_efficiencies_dont_erase_loops):.4f} true_eff_dont_erase_loops={mean(true_efficiencies_dont_erase_loops):.4f}\n"
        log_entry += f"{graph_label} {walk_variant} assm_eff_erase_loops={mean(assm_efficiencies_erase_loops):.4f} true_eff_erase_loops={mean(true_efficiencies_erase_loops):.4f}\n"
        log_entry += f"{graph_label} {walk_variant} assm_rho_dont_erase_loops={mean(assm_rho_dont_erase_loops):.4f} true_rho_dont_erase_loops={mean(true_rho_dont_erase_loops):.4f}\n"
        log_entry += f"{graph_label} {walk_variant} assm_rho_erase_loops={mean(assm_rho_erase_loops):.4f} true_rho_erase_loops={mean(true_rho_erase_loops):.4f}\n"
        log_entry += "\n"
        result_log.write(log_entry)
        result_log.flush()
        print(log_entry, flush=True)
            