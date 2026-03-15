from __future__ import annotations

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


DEFAULT_DATA_FILE = Path("data/safepairs.csv")
DEFAULT_OUTPUT = Path("plots/safepairs.pdf")
DEFAULT_RUNS = 1000
DEFAULT_VARIANT = "HS"
EXPOSURE_THRESHOLDS = list(range(50, 100))
GRAPH_SPECS = (
    ("nsfnet", "NSFNet"),
    ("geant", "GÉANT"),
    ("generated", "Generated"),
)


def load_graphs():
    from helpers.utils import graphs_dir, read_edge_list_csv, synthetic_graph_snapshot

    return [
        ("nsfnet", "NSFNet", read_edge_list_csv(graphs_dir / "nsfnet" / "edges.csv")),
        ("geant", "GÉANT", read_edge_list_csv(graphs_dir / "geant" / "edges.csv")),
        ("generated", "Generated", synthetic_graph_snapshot(99)),
    ]


def compute_rows(variant: str, no_of_runs: int, erase_loops: bool) -> list[dict[str, str]]:
    import networkx as nx
    from tqdm import tqdm

    from helpers.compute import HopStats, compute_hop_stats

    rows: list[dict[str, str]] = []

    for graph_id, graph_label, graph in load_graphs():
        biconnected_pairs: list[tuple[str, str]] = []
        for src in tqdm(graph.nodes(), desc=f"Finding biconnected pairs for {graph_label}"):
            for tgt in graph.nodes():
                if src == tgt:
                    continue
                if nx.node_connectivity(graph, src, tgt) > 1:
                    biconnected_pairs.append((str(src), str(tgt)))

        for src, tgt in tqdm(biconnected_pairs, desc=f"Computing hop stats for {graph_label}"):
            hop_stats = compute_hop_stats(
                HopStats.HopSimParams(
                    g=graph,
                    src=src,
                    tgt=tgt,
                    var=variant,
                    no_of_runs=no_of_runs,
                    erase_loops=erase_loops,
                )
            )
            rows.append(
                {
                    "graph_id": graph_id,
                    "graph_label": graph_label,
                    "variant": variant,
                    "erase_loops": str(erase_loops),
                    "src": src,
                    "tgt": tgt,
                    "exposure_pct": f"{hop_stats.exposure * 100:.6f}",
                }
            )

    return rows


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "graph_id",
                "graph_label",
                "variant",
                "erase_loops",
                "src",
                "tgt",
                "exposure_pct",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def rows_to_series(
    rows: list[dict[str, str]], variant: str, erase_loops: bool
) -> dict[str, list[float]]:
    series_by_graph: dict[str, list[float]] = {}

    for row in rows:
        if row["variant"] != variant or row["erase_loops"] != str(erase_loops):
            continue
        series_by_graph.setdefault(row["graph_label"], []).append(float(row["exposure_pct"]))

    return series_by_graph


def plot_safe_pairs(
    series_by_graph: dict[str, list[float]], output_path: Path, show_plot: bool
) -> None:
    plt.rcParams.update(
        {
            "axes.labelsize": 16,
            "xtick.labelsize": 12,
            "ytick.labelsize": 12,
            "legend.fontsize": 14,
            "axes.titlesize": 16,
        }
    )

    fig, ax = plt.subplots(figsize=(5.25, 3.5))
    style_map = {
        "NSFNet": {"color": "tab:blue", "linestyle": "-"},
        "GÉANT": {"color": "tab:orange", "linestyle": "--"},
        "Generated": {"color": "tab:green", "linestyle": "-."},
    }

    for _graph_id, graph_label in GRAPH_SPECS:
        exposures = series_by_graph.get(graph_label)
        if not exposures:
            continue

        safe_pair_fractions = [
            sum(1 for exposure in exposures if exposure <= threshold) / len(exposures)
            for threshold in EXPOSURE_THRESHOLDS
        ]
        ax.plot(
            EXPOSURE_THRESHOLDS,
            safe_pair_fractions,
            linewidth=2.0,
            label=graph_label,
            **style_map[graph_label],
        )

    if not any(series_by_graph.values()):
        raise ValueError("No exposure data found for the requested plot.")

    ax.set_xlabel(r"Exposure threshold [%]")
    ax.set_ylabel(r"Safe $(s,t)$ pairs [%]")
    ax.set_xticks([50, 60, 70, 80, 90], labels=["50", "60", "70", "80", "90"])
    ax.set_yticks([0.0, 0.25, 0.5, 0.75, 1.0], labels=["0", "25", "50", "75", "100"])
    ax.set_xlim(50, 95)
    ax.set_ylim(0.0, 1.1)
    ax.set_title("Pair safety under assumed exposure")
    ax.grid(True, which="major", linestyle="--", alpha=0.45)
    ax.legend(loc="lower right")
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format="pdf", bbox_inches="tight")
    if show_plot:
        plt.show()
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute or plot safe-pair curves from exposure simulations."
    )
    parser.add_argument(
        "--phase",
        choices=("compute", "plot"),
        default="plot",
        help="Choose whether to compute exposure data or plot an existing data file.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_FILE,
        help="CSV path used for writing computed values and reading plot input.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output PDF path for the plot.",
    )
    parser.add_argument(
        "--variant",
        default=DEFAULT_VARIANT,
        help="Random walk variant to compute and plot.",
    )
    parser.add_argument(
        "--erase-loops",
        action="store_true",
        help="Use loop-erased walks for compute and plot phases.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=DEFAULT_RUNS,
        help="Number of simulation runs per source-target pair during compute phase.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save the figure without opening an interactive plot window.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.phase == "compute":
        rows = compute_rows(
            variant=args.variant,
            no_of_runs=args.runs,
            erase_loops=args.erase_loops,
        )
        write_rows(args.data, rows)
        return

    rows = read_rows(args.data)
    series_by_graph = rows_to_series(
        rows,
        variant=args.variant,
        erase_loops=args.erase_loops,
    )
    plot_safe_pairs(
        series_by_graph=series_by_graph,
        output_path=args.output,
        show_plot=not args.no_show,
    )


if __name__ == "__main__":
    main()