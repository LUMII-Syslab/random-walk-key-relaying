from helpers.compute import (
    compute_hop_stats,
    HopStats,
    compute_tput_stats,
    ThroughputStats,
)
from helpers.utils import read_edge_list_csv, graphs_dir
import networkx as nx
from statistics import median, mean
from math import sqrt
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

FRAGMENTS = 1024
ALPHA = 0.9999

result_log = open("result.log", "a")


def prob(g, N, chi):
    a = 1.0 - chi
    # P[X >= g] for X ~ Binomial(N, a)
    return binom.sf(g - 1, N, a)


def find_g(N, chi, threshold):
    for g in range(N, -1, -1):
        if prob(g, N, chi) >= threshold:
            return g
    return -1


def summarize_metric(name, values):
    return (
        f"{name}_min={min(values):.8f} "
        f"{name}_median={median(values):.8f} "
        f"{name}_mean={mean(values):.8f} "
        f"{name}_max={max(values):.8f}"
    )


def pop_cov(xs, ys):
    assert len(xs) == len(ys)
    mx = mean(xs)
    my = mean(ys)
    return mean((x - mx) * (y - my) for x, y in zip(xs, ys))


def pop_corr(xs, ys):
    cov = pop_cov(xs, ys)
    sx = sqrt(pop_cov(xs, xs))
    sy = sqrt(pop_cov(ys, ys))
    if sx == 0.0 or sy == 0.0:
        return 0.0
    return cov / (sx * sy)


def summarize_true_eta_decomposition(name, rhos, inv_hops, etas):
    mean_rho = mean(rhos)
    mean_inv_h = mean(inv_hops)
    cov_rho_inv_h = pop_cov(rhos, inv_hops)
    corr_rho_inv_h = pop_corr(rhos, inv_hops)
    mean_eta = mean(etas)
    reconstructed_mean_eta = mean_rho * mean_inv_h + cov_rho_inv_h

    return (
        f"{name}_mean_rho={mean_rho:.8f} "
        f"{name}_mean_inv_h={mean_inv_h:.8f} "
        f"{name}_cov_rho_inv_h={cov_rho_inv_h:.8f} "
        f"{name}_corr_rho_inv_h={corr_rho_inv_h:.8f} "
        f"{name}_mean_eta={mean_eta:.8f} "
        f"{name}_reconstructed_mean_eta={reconstructed_mean_eta:.8f} "
        f"{name}_reconstruction_gap={abs(mean_eta - reconstructed_mean_eta):.12f}"
    )


def summarize_assumed_eta_decomposition(name, assumed_rho, inv_hops, etas):
    mean_inv_h = mean(inv_hops)
    mean_eta = mean(etas)
    reconstructed_mean_eta = assumed_rho * mean_inv_h

    return (
        f"{name}_mean_rho={assumed_rho:.8f} "
        f"{name}_mean_inv_h={mean_inv_h:.8f} "
        f"{name}_cov_rho_inv_h=0.00000000 "
        f"{name}_corr_rho_inv_h=0.00000000 "
        f"{name}_mean_eta={mean_eta:.8f} "
        f"{name}_reconstructed_mean_eta={reconstructed_mean_eta:.8f} "
        f"{name}_reconstruction_gap={abs(mean_eta - reconstructed_mean_eta):.12f}"
    )


for graph_id, graph_label in GRAPH_SPECS:
    g = read_edge_list_csv(graphs_dir / graph_id / "edges.csv")

    biconnected_pairs = []
    for src in tqdm(g.nodes(), desc=f"Finding biconnected pairs for {graph_label}"):
        for tgt in g.nodes():
            if src == tgt:
                continue
            if nx.node_connectivity(g, src, tgt) == 1:
                continue
            biconnected_pairs.append((src, tgt))

    for walk_variant in ["NB", "LRV", "NC", "HS"]:
        assm_efficiencies_erase_loops = []
        true_efficiencies_erase_loops = []
        assm_efficiencies_dont_erase_loops = []
        true_efficiencies_dont_erase_loops = []

        # For eta = rho * (1 / h)
        true_rhos = []
        inv_hops_dont_erase_loops = []
        inv_hops_erase_loops = []

        tputs = []
        extracted_tputs_assm = []
        extracted_tputs_true = []

        assumed_good_fragments = find_g(
            FRAGMENTS,
            ASSUMED_WORST_EXPOSURE[walk_variant],
            ALPHA,
        )
        assert 0 < assumed_good_fragments <= FRAGMENTS
        assumed_rho = assumed_good_fragments / FRAGMENTS

        for src, tgt in tqdm(
            biconnected_pairs,
            desc=f"Computing hop stats for {graph_label} {walk_variant}",
        ):
            hop_stats_no_erase_loops = compute_hop_stats(
                HopStats.HopSimParams(
                    g=g,
                    src=src,
                    tgt=tgt,
                    var=walk_variant,
                    no_of_runs=1000,
                    erase_loops=False,
                )
            )
            hop_stats_erase_loops = compute_hop_stats(
                HopStats.HopSimParams(
                    g=g,
                    src=src,
                    tgt=tgt,
                    var=walk_variant,
                    no_of_runs=1000,
                    erase_loops=True,
                )
            )

            exposure = hop_stats_no_erase_loops.exposure
            good_fragments = find_g(FRAGMENTS, exposure, ALPHA)
            assert 0 < good_fragments <= FRAGMENTS
            true_rho = good_fragments / FRAGMENTS
            true_rhos.append(true_rho)

            mean_hops_no_erase = hop_stats_no_erase_loops.mean_hops
            inv_h_no_erase = 1.0 / mean_hops_no_erase
            inv_hops_dont_erase_loops.append(inv_h_no_erase)

            assm_efficiency = assumed_rho * inv_h_no_erase
            true_efficiency = true_rho * inv_h_no_erase
            assm_efficiencies_dont_erase_loops.append(assm_efficiency)
            true_efficiencies_dont_erase_loops.append(true_efficiency)

            mean_hops_erase = hop_stats_erase_loops.mean_hops
            inv_h_erase = 1.0 / mean_hops_erase
            inv_hops_erase_loops.append(inv_h_erase)

            assm_efficiency = assumed_rho * inv_h_erase
            true_efficiency = true_rho * inv_h_erase
            assm_efficiencies_erase_loops.append(assm_efficiency)
            true_efficiencies_erase_loops.append(true_efficiency)

            tput_stats = compute_tput_stats(
                ThroughputStats.TputSimParams(
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
                )
            )
            tputs.append(tput_stats.mean_tput_bits)

            extracted_tput_assm = tput_stats.mean_tput_bits * assumed_rho
            extracted_tput_true = tput_stats.mean_tput_bits * true_rho
            extracted_tputs_assm.append(extracted_tput_assm)
            extracted_tputs_true.append(extracted_tput_true)

        log_entry = (
            f"{graph_label} {walk_variant} "
            f"{summarize_metric('assm_eff_dont_erase_loops', assm_efficiencies_dont_erase_loops)} "
            f"{summarize_metric('true_eff_dont_erase_loops', true_efficiencies_dont_erase_loops)}\n"
        )
        log_entry += (
            f"{graph_label} {walk_variant} "
            f"{summarize_assumed_eta_decomposition(
                'assm_eta_dont_erase_loops',
                assumed_rho,
                inv_hops_dont_erase_loops,
                assm_efficiencies_dont_erase_loops,
            )} "
            f"{summarize_true_eta_decomposition(
                'true_eta_dont_erase_loops',
                true_rhos,
                inv_hops_dont_erase_loops,
                true_efficiencies_dont_erase_loops,
            )}\n"
        )

        log_entry += (
            f"{graph_label} {walk_variant} "
            f"{summarize_metric('assm_eff_erase_loops', assm_efficiencies_erase_loops)} "
            f"{summarize_metric('true_eff_erase_loops', true_efficiencies_erase_loops)}\n"
        )
        log_entry += (
            f"{graph_label} {walk_variant} "
            f"{summarize_assumed_eta_decomposition(
                'assm_eta_erase_loops',
                assumed_rho,
                inv_hops_erase_loops,
                assm_efficiencies_erase_loops,
            )} "
            f"{summarize_true_eta_decomposition(
                'true_eta_erase_loops',
                true_rhos,
                inv_hops_erase_loops,
                true_efficiencies_erase_loops,
            )}\n"
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