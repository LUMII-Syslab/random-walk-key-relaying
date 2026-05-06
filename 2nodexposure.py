import json
import re
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from statistics import mean, median
from subprocess import check_output

import networkx as nx
from tqdm import tqdm

from helpers.graphs import read_geant_graph

graph = read_geant_graph()
nodes = list(graph.nodes())
DEFAULT_EXPOSURES_PATH = Path("out/exposures.json")
DEFAULT_THRESHOLDS = (0.75, 0.80, 0.85, 0.90, 0.95, 0.97, 0.99)


def compute_uv_exposures(pair):
    u, v = pair
    uv_exposures = []

    without_uv = graph.copy()
    without_uv.remove_nodes_from([u, v])

    for src in nodes:
        for tgt in nodes:
            if src == tgt:
                continue

            # if src or tgt is u or v, then skip
            if src == u or src == v or tgt == u or tgt == v:
                continue

            # if removing u, v disconnects src, tgt, then skip u,v
            if not nx.has_path(without_uv, src, tgt):
                continue

            # run the simulation from src to tgt with cartel {u,v}
            cmd = [
                "./cpp/build/hops",
                "-s", str(src),
                "-t", str(tgt),
                "-w", "HS",
                "-e", "./graphs/geant/edges.csv",
                "-n", "10000",
                "--cartel", f"{u},{v}",
            ]
            output = check_output(cmd).decode("utf-8")

            exposure = re.search(r"cartel_hit_prob_lerw: ([0-9.]+)", output).group(1)
            uv_exposures.append({"src": src, "tgt": tgt, "exposure": float(exposure)})

    return {"u": u, "v": v, "exposures": uv_exposures}


def precompute_exposures(output_path, max_workers):
    check_output(["make", "./build/hops"], cwd="cpp")

    pairs = [(u, v) for u in nodes for v in nodes if u < v]
    exposures = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(compute_uv_exposures, pair) for pair in pairs]
        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Processing malicious node pairs",
        ):
            exposures.append(future.result())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(exposures, f)


def eligible_pair_count(u, v):
    without_uv = graph.copy()
    without_uv.remove_nodes_from([u, v])
    return sum(
        len(component) * (len(component) - 1)
        for component in nx.connected_components(without_uv)
    )


def load_exposures(path):
    with path.open() as f:
        return json.load(f)


def analyze_exposures(exposures, thresholds):
    percentages_by_threshold = {threshold: [] for threshold in thresholds}

    for cartel_result in exposures:
        u = cartel_result["u"]
        v = cartel_result["v"]
        eligible_count = eligible_pair_count(u, v)
        if eligible_count == 0:
            continue

        if len(cartel_result["exposures"]) != eligible_count:
            raise ValueError(
                f"Exposure count for cartel {{{u}, {v}}} is "
                f"{len(cartel_result['exposures'])}, expected {eligible_count}"
            )

        exposure_values = [entry["exposure"] for entry in cartel_result["exposures"]]
        for threshold in thresholds:
            affected_count = sum(exposure > threshold for exposure in exposure_values)
            percentages_by_threshold[threshold].append(100 * affected_count / eligible_count)

    return {
        threshold: {
            "median": median(percentages),
            "average": mean(percentages),
            "maximum": max(percentages),
        }
        for threshold, percentages in percentages_by_threshold.items()
        if percentages
    }


def print_latex_rows(summary):
    for threshold, stats in summary.items():
        print(
            f"{threshold:.0%} & "
            f"{stats['median']:.2f}\\% & "
            f"{stats['average']:.2f}\\% & "
            f"{stats['maximum']:.2f}\\% \\\\"
        )


def main():
    parser = ArgumentParser(
        description="Precompute or analyze two-relay GÉANT HS exposure data."
    )
    parser.add_argument(
        "--precompute",
        action="store_true",
        help="run the expensive hops simulations and write the exposure JSON",
    )
    parser.add_argument(
        "--exposures",
        type=Path,
        default=DEFAULT_EXPOSURES_PATH,
        help="path to the precomputed two-relay exposure JSON",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=12,
        help="worker count used only with --precompute",
    )
    args = parser.parse_args()

    if args.precompute:
        precompute_exposures(args.exposures, args.workers)
        return

    exposures = load_exposures(args.exposures)
    summary = analyze_exposures(exposures, DEFAULT_THRESHOLDS)
    print_latex_rows(summary)


if __name__ == "__main__":
    main()