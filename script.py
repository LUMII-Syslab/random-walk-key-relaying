from helpers.compute import compute_hop_stats, HopStats, compute_tput_stats, ThroughputStats
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

ASSUMED_WORST_EXPOSURE = {
    "HS": 0.961,
    "LRV": 0.974,
    "NB": 0.973,
    "NC": 0.965,
}

result_log = open("result.log", "a")

def prob(g, N, chi):
    a = 1.0 - chi
    # P[X >= g] for X ~ Binomial(N, a)
    return binom.sf(g - 1, N, a)

def find_g(N, chi, threshold):
    for g in range(N, -1, -1):
        if prob(g, N, chi) >= threshold: return g
    return -1


def summarize_metric(name, values):
    return (
        f"{name}_min={min(values):.4f} "
        f"{name}_median={median(values):.4f} "
        f"{name}_mean={mean(values):.4f} "
        f"{name}_max={max(values):.4f}"
    )

for graph_id, graph_label in GRAPH_SPECS:
    g = read_edge_list_csv(graphs_dir / graph_id / "edges.csv")
    for walk_variant in ['NB', 'LRV', 'NC', 'HS']:
        biconnected_pairs = []
        for src in tqdm(g.nodes(), desc=f"Finding biconnected pairs for {graph_label}"):
            for tgt in g.nodes():
                if src == tgt: continue
                if nx.node_connectivity(g, src, tgt) == 1: continue
                biconnected_pairs.append((src, tgt))
        assm_efficiencies_erase_loops = []
        true_efficiencies_erase_loops = []
        assm_efficiencies_dont_erase_loops = []
        true_efficiencies_dont_erase_loops = []

        tputs = []
        extracted_tputs_assm = []
        extracted_tputs_true = []
        FRAGMENTS, ALPHA = 1024, 0.9999
        assumed_good_fragments = find_g(
            FRAGMENTS,
            ASSUMED_WORST_EXPOSURE[walk_variant],
            ALPHA,
        )
        assert assumed_good_fragments > 0
        assert assumed_good_fragments <= FRAGMENTS

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

            exposure = hop_stats_no_erase_loops.exposure
            good_fragments = find_g(FRAGMENTS, exposure, ALPHA)
            assert good_fragments > 0
            assert good_fragments <= FRAGMENTS

            mean_hops = hop_stats_no_erase_loops.mean_hops
            assm_efficiency = (assumed_good_fragments / FRAGMENTS) / mean_hops
            true_efficiency = (good_fragments / FRAGMENTS) / mean_hops
            assm_efficiencies_dont_erase_loops.append(assm_efficiency)
            true_efficiencies_dont_erase_loops.append(true_efficiency)

            mean_hops = hop_stats_erase_loops.mean_hops
            assm_efficiency = (assumed_good_fragments / FRAGMENTS) / mean_hops
            true_efficiency = (good_fragments / FRAGMENTS) / mean_hops
            assm_efficiencies_erase_loops.append(assm_efficiency)
            true_efficiencies_erase_loops.append(true_efficiency)

            tput_stats = compute_tput_stats(ThroughputStats.TputSimParams(
                g=g,
                chunk_size_bits=256,
                latency_s=0.05,
                link_buff_sz_bits=10**9,
                print_arrival_times=False,
                qkd_skr_bits_per_s=1000,
                relay_buffer_sz_chunks=10**9,
                sim_duration_s=1000,
                src=src,
                tgt=tgt,
                var=walk_variant,
                erase_loops=True,
            ))
            tputs.append(tput_stats.mean_tput_bits)
            
            extracted_tput_assm = (
                tput_stats.mean_tput_bits * assumed_good_fragments / FRAGMENTS
            )
            extracted_tput_true = (
                tput_stats.mean_tput_bits * good_fragments / FRAGMENTS
            )
            extracted_tputs_assm.append(extracted_tput_assm)
            extracted_tputs_true.append(extracted_tput_true)

        log_entry = (
            f"{graph_label} {walk_variant} "
            f"{summarize_metric('assm_eff_dont_erase_loops', assm_efficiencies_dont_erase_loops)} "
            f"{summarize_metric('true_eff_dont_erase_loops', true_efficiencies_dont_erase_loops)}\n"
        )
        log_entry += (
            f"{graph_label} {walk_variant} "
            f"{summarize_metric('assm_eff_erase_loops', assm_efficiencies_erase_loops)} "
            f"{summarize_metric('true_eff_erase_loops', true_efficiencies_erase_loops)}\n"
        )
        log_entry += (
            f"{graph_label} {walk_variant} "
            f"{summarize_metric('tput', tputs)} "
            f"{summarize_metric('extracted_tput_assm', extracted_tputs_assm)} "
            f"{summarize_metric('extracted_tput_true', extracted_tputs_true)}\n"
        )
        log_entry += "\n"
        result_log.write(log_entry)
        result_log.flush()
        print(log_entry, flush=True)
            