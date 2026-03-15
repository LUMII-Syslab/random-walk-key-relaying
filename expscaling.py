from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt


DATA_FILE = Path("data/scaling.txt")
DEFAULT_OUTPUT = Path("plots/max_exposure_scaling.pdf")
DEFAULT_MIN_NODE_COUNT = 36
WALK_VARIANTS = ("NB", "LRV", "NC", "HS")
PROCESSING_RE = re.compile(
    r"^Processing\s+(?P<nodes>\d+)\s+nodes\.\.\.\s+with\s+erase_loops=(?P<erase_loops>False|True)$"
)
MAX_EXPOSURE_RE = re.compile(
    r"^(?P<variant>NB|LRV|NC|HS):\s+max_exposure=(?P<max_exposure>\d+(?:\.\d+)?)\b"
)


def parse_scaling(path: Path) -> dict[bool, dict[str, dict[int, float]]]:
    data: dict[bool, dict[str, dict[int, float]]] = {False: {}, True: {}}
    current_nodes: int | None = None
    current_erase_loops: bool | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        processing_match = PROCESSING_RE.match(line)
        if processing_match:
            current_nodes = int(processing_match.group("nodes"))
            current_erase_loops = processing_match.group("erase_loops") == "True"
            continue

        exposure_match = MAX_EXPOSURE_RE.match(line)
        if exposure_match:
            if current_nodes is None or current_erase_loops is None:
                raise ValueError(f"Found exposure line before any processing block: {line}")

            variant = exposure_match.group("variant")
            max_exposure = float(exposure_match.group("max_exposure"))
            points = data[current_erase_loops].setdefault(variant, {})

            if current_nodes in points:
                raise ValueError(
                    f"Duplicate max_exposure entry for {variant} at {current_nodes=} "
                    f"and {current_erase_loops=}"
                )

            points[current_nodes] = max_exposure

    return data


def plot_max_exposure(
    series_by_variant: dict[str, dict[int, float]],
    erase_loops: bool,
    output_path: Path,
    min_node_count: int,
) -> None:
    plt.rcParams.update(
        {
            "axes.labelsize": 14,
            "xtick.labelsize": 12,
            "ytick.labelsize": 12,
            "legend.fontsize": 14,
            "axes.titlesize": 16,
        }
    )

    fig, ax = plt.subplots(figsize=(6, 4))
    style_map = {
        "NB": {"color": "tab:blue", "linestyle": "-"},
        "LRV": {"color": "tab:orange", "linestyle": "--"},
        "NC": {"color": "tab:green", "linestyle": "-."},
        "HS": {"color": "tab:red", "linestyle": ":"},
    }

    for variant in WALK_VARIANTS:
        node_to_exposure = series_by_variant.get(variant)
        if not node_to_exposure:
            continue

        node_counts = sorted(
            node_count for node_count in node_to_exposure if node_count >= min_node_count
        )
        if not node_counts:
            continue
        exposures = [node_to_exposure[node_count] for node_count in node_counts]
        ax.plot(
            node_counts,
            exposures,
            linewidth=2.0,
            label=variant,
            **style_map[variant],
        )

    all_node_counts = sorted(
        {
            node_count
            for node_to_exposure in series_by_variant.values()
            for node_count in node_to_exposure
            if node_count >= min_node_count
        }
    )
    if all_node_counts:
        major_xticks = [node_count for node_count in all_node_counts if node_count % 9 == 0]
        minor_xticks = [
            node_count
            for node_count in all_node_counts
            if node_count % 3 == 0 and node_count % 9 != 0
        ]
        ax.set_xticks(major_xticks)
        if minor_xticks:
            ax.set_xticks(minor_xticks, minor=True)
        ax.set_xlim(left=min_node_count)

    ax.set_xlabel(r"Number of nodes, $|V|$")
    ax.set_ylabel(r"Worst-case exposure (\%)")
    ax.set_yticks([0.91, 0.93, 0.95, 0.97], labels=["91", "93", "95", "97"])
    ax.set_title("Worst-case exposure vs. network size")
    ax.grid(True, which="major", linestyle="--", alpha=0.45)
    ax.legend(loc="lower right")
    fig.tight_layout()

    plt.show()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format="pdf", bbox_inches="tight")
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot max exposure versus node count for each walk variant."
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=DATA_FILE,
        help="Path to the scaling results text file.",
    )
    parser.add_argument(
        "--erase-loops",
        action="store_true",
        help="Plot the erase_loops=True series instead of the default erase_loops=False series.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Output PDF path for the plot.",
    )
    parser.add_argument(
        "--min-node-count",
        type=int,
        default=DEFAULT_MIN_NODE_COUNT,
        help="Smallest node count to include in the plot.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = parse_scaling(args.data)
    plot_max_exposure(
        series_by_variant=data[args.erase_loops],
        erase_loops=args.erase_loops,
        output_path=args.output,
        min_node_count=args.min_node_count,
    )


if __name__ == "__main__":
    main()
