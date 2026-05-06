import json
import re
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations
from pathlib import Path
from statistics import mean, median
from subprocess import check_output

import networkx as nx
from tqdm import tqdm

from helpers.graphs import read_geant_graph

graph = read_geant_graph()
nodes = list(graph.nodes())
DEFAULT_EXPOSURES_PATH = Path("out/exposures-3nodes.json")
DEFAULT_THRESHOLDS = (0.75, 0.80, 0.85, 0.90, 0.95, 0.97, 0.99)
HOP_VARIANT = "HS"
HOP_RUNS = 10000
GEANT_EDGES_PATH = "./graphs/geant/edges.csv"


def cartel_nodes_from_result(cartel_result):
    if "cartel" in cartel_result:
        return cartel_result["cartel"]
    return [cartel_result["u"], cartel_result["v"]]


def hop_command(src, tgt, cartel=None):
    cmd = [
        "./cpp/build/hops",
        "-s",
        str(src),
        "-t",
        str(tgt),
        "-w",
        HOP_VARIANT,
        "-e",
        GEANT_EDGES_PATH,
        "-n",
        str(HOP_RUNS),
    ]
    if cartel is not None:
        cmd.extend(["--cartel", ",".join(map(str, cartel))])
    return cmd


def run_hop_simulation(src, tgt, cartel=None):
    return check_output(hop_command(src, tgt, cartel)).decode("utf-8")


def warm_hops_cache(max_workers):
    src_tgt_pairs = [(src, tgt) for src in nodes for tgt in nodes if src != tgt]
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(run_hop_simulation, src, tgt)
            for src, tgt in src_tgt_pairs
        ]
        for future in tqdm(
            as_completed(futures),
            total=len(src_tgt_pairs),
            desc="Warming hops cache for source-target pairs",
        ):
            future.result()


def compute_cartel_exposures(cartel):
    cartel = tuple(cartel)
    cartel_set = set(cartel)
    cartel_exposures = []

    without_cartel = graph.copy()
    without_cartel.remove_nodes_from(cartel)

    for src in nodes:
        for tgt in nodes:
            if src == tgt:
                continue

            # If src or tgt is controlled by the cartel, it is not an exposure case.
            if src in cartel_set or tgt in cartel_set:
                continue

            # If removing the cartel disconnects src and tgt, the cartel is unavoidable.
            if not nx.has_path(without_cartel, src, tgt):
                continue

            output = run_hop_simulation(src, tgt, cartel)

            exposure = re.search(r"cartel_hit_prob_lerw: ([0-9.]+)", output).group(1)
            cartel_exposures.append({"src": src, "tgt": tgt, "exposure": float(exposure)})

    return {"cartel": list(cartel), "exposures": cartel_exposures}


def precompute_exposures(output_path, max_workers, cartel_size, warm_cache):
    check_output(["make", "./build/hops"], cwd="cpp")

    if warm_cache:
        warm_hops_cache(max_workers)

    cartels = list(combinations(nodes, cartel_size))
    exposures = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(compute_cartel_exposures, cartel) for cartel in cartels]
        for future in tqdm(
            as_completed(futures),
            total=len(cartels),
            desc=f"Processing malicious {cartel_size}-node cartels",
        ):
            exposures.append(future.result())

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(exposures, f)


def eligible_pair_count(cartel):
    without_cartel = graph.copy()
    without_cartel.remove_nodes_from(cartel)
    return sum(
        len(component) * (len(component) - 1)
        for component in nx.connected_components(without_cartel)
    )


def load_exposures(path):
    with path.open() as f:
        return json.load(f)


def analyze_exposures(exposures, thresholds):
    percentages_by_threshold = {threshold: [] for threshold in thresholds}

    for cartel_result in exposures:
        cartel = cartel_nodes_from_result(cartel_result)
        eligible_count = eligible_pair_count(cartel)
        if eligible_count == 0:
            continue

        if len(cartel_result["exposures"]) != eligible_count:
            raise ValueError(
                f"Exposure count for cartel {{{', '.join(map(str, cartel))}}} is "
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
        description="Precompute or analyze multi-relay GÉANT HS exposure data."
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
        help="path to the precomputed exposure JSON",
    )
    parser.add_argument(
        "--cartel-size",
        type=int,
        choices=(2, 3),
        default=3,
        help="number of malicious relay nodes used with --precompute",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=12,
        help="worker count used only with --precompute",
    )
    parser.add_argument(
        "--skip-cache-warmup",
        action="store_true",
        help="skip the preliminary source-target cache warm-up used with --precompute",
    )
    args = parser.parse_args()

    if args.precompute:
        precompute_exposures(
            args.exposures,
            args.workers,
            args.cartel_size,
            not args.skip_cache_warmup,
        )
        return

    exposures = load_exposures(args.exposures)
    summary = analyze_exposures(exposures, DEFAULT_THRESHOLDS)
    print_latex_rows(summary)


if __name__ == "__main__":
    main()