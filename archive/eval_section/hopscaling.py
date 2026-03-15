from __future__ import annotations

import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt


DATA_FILE = Path("data/scaling.txt")
OUTPUT_DIR = Path("plots")
WALK_VARIANTS = ("NB", "LRV", "NC", "HS")
PROCESSING_RE = re.compile(
    r"^Processing\s+(?P<nodes>\d+)\s+nodes\.\.\.\s+with\s+erase_loops=(?P<erase_loops>False|True)$"
)
MEAN_HOPS_RE = re.compile(
    r"^(?P<variant>NB|LRV|NC|HS):\s+avg_mean_hop_count=(?P<avg_mean_hop_count>\d+)\b"
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

        mean_hops_match = MEAN_HOPS_RE.match(line)
        if mean_hops_match:
            if current_nodes is None or current_erase_loops is None:
                raise ValueError(f"Found hop-count line before a processing block: {line}")

            variant = mean_hops_match.group("variant")
            avg_mean_hop_count = float(mean_hops_match.group("avg_mean_hop_count"))
            points = data[current_erase_loops].setdefault(variant, {})

            if current_nodes in points:
                raise ValueError(
                    f"Duplicate avg_mean_hop_count entry for {variant} at {current_nodes=} "
                    f"and {current_erase_loops=}"
                )

            points[current_nodes] = avg_mean_hop_count

    return data


def plot_avg_mean_hop_count(
    series_by_variant: dict[str, dict[int, float]],
    erase_loops: bool,
    output_path: Path,
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
        "NB": {"color": "tab:blue", "linestyle": "-"},
        "LRV": {"color": "tab:orange", "linestyle": "--"},
        "NC": {"color": "tab:green", "linestyle": "-."},
        "HS": {"color": "tab:red", "linestyle": ":"},
    }

    for variant in WALK_VARIANTS:
        node_to_hops = series_by_variant.get(variant)
        if not node_to_hops:
            continue

        node_counts = sorted(node_to_hops)
        avg_mean_hop_counts = [node_to_hops[node_count] for node_count in node_counts]
        ax.plot(
            node_counts,
            avg_mean_hop_counts,
            linewidth=2.0,
            label=variant,
            **style_map[variant],
        )

    all_node_counts = sorted(
        {
            node_count
            for node_to_hops in series_by_variant.values()
            for node_count in node_to_hops
        }
    )
    if not all_node_counts:
        raise ValueError(f"No hop-count data found for {erase_loops=}.")

    major_xticks = [node_count for node_count in all_node_counts if node_count % 9 == 0]
    minor_xticks = [
        node_count
        for node_count in all_node_counts
        if node_count % 3 == 0 and node_count % 9 != 0
    ]
    ax.set_xticks(major_xticks)
    if minor_xticks:
        ax.set_xticks(minor_xticks, minor=True)
    ax.set_xlim(all_node_counts[0], all_node_counts[-1])

    all_hop_counts = [
        hop_count for node_to_hops in series_by_variant.values() for hop_count in node_to_hops.values()
    ]
    max_hop_count = max(all_hop_counts)
    y_max = ((int(max_hop_count) + 9) // 10) * 10
    ax.set_yticks(list(range(0, y_max + 1, 10)))
    ax.set_ylim(0, y_max)

    mode = "with loop erasure" if erase_loops else "without loop erasure"
    ax.set_xlabel(r"Number of nodes $|V|$")
    ax.set_ylabel(r"Mean $\hat\mathrm{\mathbb{E}}[\mathrm{H}_{s,t}]$")

    ax.set_title(fr"Mean hop count vs. $|V|$ ( $\ell$.e. {'on' if erase_loops else 'off'} )")
    ax.grid(True, which="major", linestyle="--", alpha=0.45)
    ax.legend(loc="upper left")
    # ax.set_ylim(0, 80)
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format="pdf", bbox_inches="tight")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot average mean hop count versus network size from scaling.txt."
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=DATA_FILE,
        help="Path to the scaling results text file.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory where the plot PDFs will be written.",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Save the figures without opening interactive plot windows.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = parse_scaling(args.data)

    plot_avg_mean_hop_count(
        series_by_variant=data[False],
        erase_loops=False,
        output_path=args.output_dir / "avg_mean_hop_count_without_loop_erasure.pdf",
    )
    plot_avg_mean_hop_count(
        series_by_variant=data[True],
        erase_loops=True,
        output_path=args.output_dir / "avg_mean_hop_count_with_loop_erasure.pdf",
    )

    if not args.no_show:
        plt.show()


if __name__ == "__main__":
    main()
