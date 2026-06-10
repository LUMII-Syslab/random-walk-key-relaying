"""Recompute mean throughput (Table tab:rw-throughput).

Calls ``cpp/build/tput`` per biconnected ordered pair (loop-erased payload routes)
and ``cpp/build/exposure`` for pair-specific yield, with joblib caching.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from pathlib import Path

import networkx as nx
import numpy as np
import tqdm
from joblib import Memory

from efficiency import (
    EXPOSURE_RUNS,
    MAX_CARTEL_SIZE,
    VARIANTS,
    biconnected_ordered_pairs,
    get_max_cartel_exposure,
    graph_specs,
    node_label,
)

ROOT = Path(__file__).resolve().parent
CPP_DIR = ROOT / "cpp"
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "random-walk-relaying")
memory = Memory(location=CACHE_DIR, verbose=0)

LATENCY_S = 0.005  # 5 ms, matching Sec. throughput prose
SIM_DURATION_S = 1000.0
QKD_SKR_BITS_PER_S = 1000.0


def _parse_mean_tput_bits(stdout: str) -> float:
    match = re.search(r"^mean_tput_bits:\s*(\d+)", stdout, re.M)
    if not match:
        raise RuntimeError(f"no mean_tput_bits in tput output:\n{stdout}")
    return float(match.group(1))


@memory.cache
def get_mean_tput_kbit_s(
    src: str,
    tgt: str,
    graph_arg: str,
    rw_variant: str,
) -> float:
    result = subprocess.run(
        [
            "./build/tput",
            "-s",
            src,
            "-t",
            tgt,
            "-g",
            graph_arg,
            "-w",
            rw_variant,
            "--erase-loops",
            "--latency-s",
            str(LATENCY_S),
            "--sim-duration-s",
            str(SIM_DURATION_S),
            "--qkd-skr-bits-per-s",
            str(QKD_SKR_BITS_PER_S),
        ],
        capture_output=True,
        text=True,
        cwd=CPP_DIR,
        check=True,
    )
    return _parse_mean_tput_bits(result.stdout) / 1000.0


def pair_throughputs(
    src: str,
    tgt: str,
    graph_arg: str,
    rw_variant: str,
    kappa: int,
) -> tuple[float, float]:
    t_kbit_s = get_mean_tput_kbit_s(src, tgt, graph_arg, rw_variant)
    cartel_size = min(kappa - 1, MAX_CARTEL_SIZE)
    chi = get_max_cartel_exposure(
        src, tgt, graph_arg, rw_variant, cartel_size, EXPOSURE_RUNS
    )
    rho = 1.0 - chi
    return t_kbit_s, t_kbit_s * rho


def summarize_graph(spec) -> dict[str, dict[str, float]]:
    pairs = biconnected_ordered_pairs(spec.nx_graph)
    node_lookup = {node_label(v): v for v in spec.nx_graph.nodes()}
    kappa_cache: dict[tuple[str, str], int] = {}
    for s, t in pairs:
        kappa_cache[(s, t)] = nx.node_connectivity(
            spec.nx_graph, node_lookup[s], node_lookup[t]
        )

    out: dict[str, dict[str, list[float]]] = {
        variant: {"T": [], "R": []} for variant in VARIANTS
    }
    for variant in VARIANTS:
        for src, tgt in tqdm.tqdm(pairs, desc=f"{spec.label} {variant} tput"):
            t_kbit_s, r_kbit_s = pair_throughputs(
                src,
                tgt,
                spec.graph_arg,
                variant,
                kappa_cache[(src, tgt)],
            )
            out[variant]["T"].append(t_kbit_s)
            out[variant]["R"].append(r_kbit_s)

    return {
        variant: {
            metric: float(np.mean(values)) for metric, values in per_variant.items()
        }
        for variant, per_variant in out.items()
    }


def format_val(x: float) -> str:
    if x >= 1.0:
        return f"{x:.2f}"
    return f"{x:.2f}"


def print_table(results: dict[str, dict[str, dict[str, float]]]) -> None:
    print("\nLaTeX rows:")
    for graph_label in ("NSFNET", "GEANT"):
        if graph_label not in results:
            continue
        res = results[graph_label]
        t_vals = " & ".join(format_val(res[v]["T"]) for v in VARIANTS)
        r_vals = " & ".join(format_val(res[v]["R"]) for v in VARIANTS)
        print(f"$T_{{s,t}}$ & {graph_label} & {t_vals} \\\\")
        print(f"$R_{{s,t}}$ & {graph_label} & {r_vals} \\\\")

    print("\nSummary:")
    for graph_label, res in results.items():
        print(f"\n{graph_label}")
        print(f"{'variant':>8}  {'T [kbit/s]':>10}  {'R [kbit/s]':>10}")
        for variant in VARIANTS:
            print(
                f"{variant:>8}  {res[variant]['T']:10.2f}  {res[variant]['R']:10.2f}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graph",
        choices=["deployed", "NSFNET", "GEANT", "all"],
        default="deployed",
    )
    args = parser.parse_args()

    subprocess.run(["make", "-C", str(CPP_DIR), "tput", "exposure"], check=True)

    if args.graph == "deployed":
        specs = graph_specs(include_generated=False)
    elif args.graph == "all":
        specs = graph_specs(include_generated=True)
    else:
        specs = [s for s in graph_specs(include_generated=True) if s.label == args.graph]

    results: dict[str, dict[str, dict[str, float]]] = {}
    for spec in specs:
        results[spec.label] = summarize_graph(spec)

    print_table(results)


if __name__ == "__main__":
    main()
