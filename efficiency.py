"""Recompute topology-wide mean RW efficiency (Table tab:rw-efficiency).

Calls ``cpp/build/hops`` and ``cpp/build/exposure`` per biconnected ordered pair,
caches with joblib, and reports mean design-threshold efficiency
:math:`\\overline{\\eta}^\\tau` and pair-specific efficiency :math:`\\overline{\\eta}`.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import numpy as np
import tqdm
from joblib import Memory
from scipy.stats import binom

from graphs import GEANT, NSFNET, get_graph_nx_graph
from graphs.generated import synthetic_graph_snapshot

ROOT = Path(__file__).resolve().parent
CPP_DIR = ROOT / "cpp"
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "random-walk-relaying")
memory = Memory(location=CACHE_DIR, verbose=0)

VARIANTS = ("NB", "LRV", "NC", "HS")
M = 1024
ALPHA = 0.9999
HOP_RUNS = 1000
EXPOSURE_RUNS = 10_000
MAX_CARTEL_SIZE = 3  # ``exposure.cpp`` inclusion-exclusion limit

# Design threshold tau per graph and variant: max single-relay exposure from
# Subsec. single-node exposure (tab:rw-exposure-overview).
GRAPH_TAU: dict[str, dict[str, float]] = {
    "NSFNET": {"NB": 0.781, "LRV": 0.774, "NC": 0.728, "HS": 0.710},
    "GEANT": {"NB": 0.957, "LRV": 0.953, "NC": 0.936, "HS": 0.913},
}


def prob(g: int, n: int, chi: float) -> float:
    a = 1.0 - chi
    return float(binom.sf(g - 1, n, a))


def find_g(n: int, chi: float, threshold: float) -> int:
    for g in range(n, -1, -1):
        if prob(g, n, chi) >= threshold:
            return g
    return 0


@dataclass(frozen=True)
class GraphSpec:
    label: str
    graph_arg: str
    nx_graph: nx.Graph


def graph_specs(include_generated: bool = False) -> list[GraphSpec]:
    specs = [
        GraphSpec("NSFNET", "nsfnet", get_graph_nx_graph("NSFNET")),
        GraphSpec("GEANT", "geant", get_graph_nx_graph("GEANT")),
    ]
    if include_generated:
        specs.append(
            GraphSpec(
                "Generated",
                str(ROOT / "graphs" / "generated" / "edges.csv"),
                nx.Graph(synthetic_graph_snapshot(99)),
            )
        )
    return specs


def node_label(node: object) -> str:
    return str(node)


def biconnected_ordered_pairs(g: nx.Graph) -> list[tuple[str, str]]:
    nodes = list(g.nodes())
    pairs: list[tuple[str, str]] = []
    for s in nodes:
        for t in nodes:
            if s == t:
                continue
            if nx.node_connectivity(g, s, t) >= 2:
                pairs.append((node_label(s), node_label(t)))
    return pairs


def _parse_mean_hops(stdout: str) -> float:
    match = re.search(r"^mean:\s*([\d.]+)", stdout, re.M)
    if not match:
        raise RuntimeError(f"no mean line in hops output:\n{stdout}")
    return float(match.group(1))


def _parse_max_exposure(stdout: str) -> float:
    match = re.search(r"^max_exposure_eligible:\s*(\S+)", stdout, re.M)
    if not match or match.group(1) == "n/a":
        raise RuntimeError(f"no max_exposure_eligible in exposure output:\n{stdout}")
    return float(match.group(1))


@memory.cache
def get_mean_hops(
    src: str,
    tgt: str,
    graph_arg: str,
    rw_variant: str,
    erase_loops: bool,
    no_of_runs: int,
) -> float:
    cmd = [
        "./build/hops",
        "-s",
        src,
        "-t",
        tgt,
        "-g",
        graph_arg,
        "-w",
        rw_variant,
        "-n",
        str(no_of_runs),
    ]
    if erase_loops:
        cmd.append("--erase-loops")
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=CPP_DIR,
        check=True,
    )
    return _parse_mean_hops(result.stdout)


@memory.cache
def get_max_cartel_exposure(
    src: str,
    tgt: str,
    graph_arg: str,
    rw_variant: str,
    cartel_size: int,
    no_of_runs: int,
) -> float:
    try:
        result = subprocess.run(
            [
                "./build/exposure",
                "-s",
                src,
                "-t",
                tgt,
                "-g",
                graph_arg,
                "-w",
                rw_variant,
                "-n",
                str(no_of_runs),
                "-m",
                str(cartel_size),
            ],
            capture_output=True,
            text=True,
            cwd=CPP_DIR,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            f"exposure failed for {src}->{tgt} ({rw_variant}, m={cartel_size}): "
            f"{exc.stderr or exc.stdout}"
        ) from exc
    return _parse_max_exposure(result.stdout)


def rho_tau_from_tau(tau: float) -> float:
    return find_g(M, tau, ALPHA) / M


def graph_tau_by_variant(spec: GraphSpec) -> dict[str, float]:
    """Per-graph tau from tab:rw-exposure-overview (Subsec. single-node exposure)."""
    if spec.label not in GRAPH_TAU:
        raise KeyError(f"no GRAPH_TAU entry for {spec.label}")
    return dict(GRAPH_TAU[spec.label])


def pair_efficiencies(
    src: str,
    tgt: str,
    graph_arg: str,
    rw_variant: str,
    erase_loops: bool,
    kappa: int,
    rho_tau: float,
) -> tuple[float, float]:
    mean_hops = get_mean_hops(
        src, tgt, graph_arg, rw_variant, erase_loops, HOP_RUNS
    )
    if mean_hops <= 0:
        raise RuntimeError(f"non-positive mean hop count for {src}->{tgt}")
    cartel_size = min(kappa - 1, MAX_CARTEL_SIZE)
    chi = get_max_cartel_exposure(
        src, tgt, graph_arg, rw_variant, cartel_size, EXPOSURE_RUNS
    )
    rho_chi = 1.0 - chi
    eta_chi = 100.0 * rho_chi / mean_hops
    eta_tau = 100.0 * rho_tau / mean_hops
    return eta_tau, eta_chi


def summarize_graph(
    spec: GraphSpec,
) -> tuple[dict[str, float], dict[str, dict[str, dict[str, float]]]]:
    tau_by_variant = graph_tau_by_variant(spec)
    rho_tau_by_variant = {
        variant: rho_tau_from_tau(tau) for variant, tau in tau_by_variant.items()
    }
    pairs = biconnected_ordered_pairs(spec.nx_graph)
    node_lookup = {node_label(v): v for v in spec.nx_graph.nodes()}
    kappa_cache: dict[tuple[str, str], int] = {}
    for s, t in pairs:
        kappa_cache[(s, t)] = nx.node_connectivity(
            spec.nx_graph, node_lookup[s], node_lookup[t]
        )

    out: dict[str, dict[str, dict[str, float]]] = {
        variant: {"tau": {"off": [], "on": []}, "chi": {"off": [], "on": []}}
        for variant in VARIANTS
    }

    for variant in VARIANTS:
        for erase_loops, key in ((False, "off"), (True, "on")):
            for src, tgt in tqdm.tqdm(
                pairs,
                desc=f"{spec.label} {variant} LE={'on' if erase_loops else 'off'}",
            ):
                eta_tau, eta_chi = pair_efficiencies(
                    src,
                    tgt,
                    spec.graph_arg,
                    variant,
                    erase_loops,
                    kappa_cache[(src, tgt)],
                    rho_tau_by_variant[variant],
                )
                out[variant]["tau"][key].append(eta_tau)
                out[variant]["chi"][key].append(eta_chi)

    results = {
        variant: {
            metric: {le: float(np.mean(values)) for le, values in by_le.items()}
            for metric, by_le in per_variant.items()
        }
        for variant, per_variant in out.items()
    }
    return tau_by_variant, results


def format_table_value(x: float, metric: str) -> str:
    if metric == "tau":
        return f"{x:.2f}"
    return f"{x:.1f}"


def print_graph_tau(
    graph_label: str,
    tau_by_variant: dict[str, float],
) -> None:
    print(f"\n{graph_label} design thresholds tau = max single-relay exposure:")
    for variant in VARIANTS:
        tau = tau_by_variant[variant]
        g_star = find_g(M, tau, ALPHA)
        print(
            f"  {variant}: tau={100 * tau:.1f}%  "
            f"g*={g_star}  rho^tau={g_star / M:.6f}"
        )


def print_efficiency_table(
    graph_label: str,
    computed: dict[str, dict[str, dict[str, float]]],
) -> None:
    print(f"\n{graph_label} mean efficiency (%)")
    print(f"{'metric':>6} {'LE':>4}  " + "  ".join(f"{v:>6}" for v in VARIANTS))
    print("-" * 44)
    for metric in ("tau", "chi"):
        for le in ("off", "on"):
            computed_vals = tuple(computed[v][metric][le] for v in VARIANTS)
            computed_str = "  ".join(
                format_table_value(v, metric).rjust(6) for v in computed_vals
            )
            print(f"{metric:>6} {le:>4}  {computed_str}")


def print_latex_row(
    graph_label: str,
    metric_key: str,
    metric_label: str,
    computed: dict[str, dict[str, dict[str, float]]],
) -> None:
    vals = []
    for le in ("off", "on"):
        for variant in VARIANTS:
            vals.append(format_table_value(computed[variant][metric_key][le], metric_key))
    joined = " & ".join(vals)
    print(f"{graph_label} & ${metric_label}$ & {joined} \\\\")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--graph",
        choices=["deployed", "NSFNET", "GEANT", "Generated", "all"],
        default="deployed",
        help="deployed = NSFNET + GEANT (default); all includes Generated",
    )
    args = parser.parse_args()

    subprocess.run(["make", "-C", str(CPP_DIR), "hops", "exposure"], check=True)

    if args.graph in ("deployed", "all"):
        specs = graph_specs(include_generated=args.graph == "all")
    else:
        specs = [s for s in graph_specs(include_generated=True) if s.label == args.graph]

    all_results: dict[str, dict[str, dict[str, dict[str, float]]]] = {}
    for spec in specs:
        tau_by_variant, all_results[spec.label] = summarize_graph(spec)
        print_graph_tau(spec.label, tau_by_variant)
        print_efficiency_table(spec.label, all_results[spec.label])

    print("\nLaTeX rows (computed):")
    for spec in specs:
        res = all_results[spec.label]
        print_latex_row(spec.label, "tau", r"\overline{\eta}^\tau", res)
        print_latex_row(spec.label, "chi", r"\overline{\eta}^{\hat{\chi}}", res)


if __name__ == "__main__":
    main()
