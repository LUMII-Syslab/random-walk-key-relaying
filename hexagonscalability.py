"""Convergence time vs hexagon-graph size (interactive).

For each CC-spiral hexagon milestone on the N=4 grid, writes a snapshot
``edges.csv`` and runs ``cpp/build/scouted`` to measure minutes until source
``1`` reaches the watermark for every other vertex.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import signal
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import tqdm
from joblib import Memory

ROOT = Path(__file__).resolve().parent
GENGRAPH_PATH = ROOT / "graphs" / "hexagon" / "gengraph.py"
spec = spec_from_file_location("hexagon_gengraph", GENGRAPH_PATH)
hexagon_gengraph = module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(hexagon_gengraph)

HEXAGON_N = hexagon_gengraph.N
build_hexagon_graph = hexagon_gengraph.build_hexagon_graph
hexagon_vertex_milestones = hexagon_gengraph.hexagon_vertex_milestones
snapshot_directed_edges = hexagon_gengraph.snapshot_directed_edges

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "random-walk-relaying")
SNAPSHOT_DIR = Path(CACHE_DIR) / "hexagon-snapshots"
memory = Memory(location=CACHE_DIR, verbose=0)

HALT_RE = re.compile(r"Halted at ([\d\.]+) seconds")


def signal_handler(sig, frame):
    plt.ioff()
    plt.show()
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)


def snapshot_csv_path(vertices: int) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    return SNAPSHOT_DIR / f"hexagon-n{vertices}.csv"


def write_snapshot_csv(vertices: int, all_edges: list[tuple[int, int]]) -> Path:
    path = snapshot_csv_path(vertices)
    edges = snapshot_directed_edges(vertices, all_edges)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Source", "Target"])
        for src, tgt in edges:
            writer.writerow([src, tgt])
    return path


@memory.cache
def get_hexagon_scalability_data_point(
    vertices: int,
    src_node: str,
    useful_scouts_only: bool,
    block_chunks: int,
    ttl: int,
    scout_emission_rate: float,
) -> float:
    all_edges, _, _ = build_hexagon_graph(HEXAGON_N)
    csv_path = write_snapshot_csv(vertices, all_edges)
    cmd = [
        "./build/scouted",
        "-g",
        str(csv_path),
        "-S",
        src_node,
        "--block-chunks",
        str(block_chunks),
        "--ttl",
        str(ttl),
        "--scout-emission-rate",
        str(scout_emission_rate),
    ]
    if useful_scouts_only:
        cmd.append("--useful-scouts-only")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(ROOT / "cpp"),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"scouted failed for {vertices} vertices (rc={result.returncode}):\n"
            f"{result.stdout}\n{result.stderr}"
        )
    match = HALT_RE.search(result.stdout)
    if not match:
        raise RuntimeError(
            f"no halt line for {vertices} vertices:\n{result.stdout}\n{result.stderr}"
        )
    return float(match.group(1))


def pick_x_major_ticks(max_vertices: int) -> list[int]:
    majors = [t for t in (16, 32, 48, 64, 80, 96) if t <= max_vertices]
    if not majors or majors[-1] != max_vertices:
        if max_vertices not in majors:
            majors.append(max_vertices)
    return sorted(set(majors))


Y_MAX_MIN = 70
Y_MAJOR_STEP_MIN = 10


def configure_y_axis(ax) -> None:
    majors = list(range(0, Y_MAX_MIN + 1, Y_MAJOR_STEP_MIN))
    ax.set_ylim(0, Y_MAX_MIN * 60)
    ax.set_yticks([m * 60 for m in majors])
    ax.set_yticklabels([f"{m} min" for m in majors])
    ax.tick_params(axis="y", which="major", length=8)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src-node", default="1")
    parser.add_argument("--block-chunks", type=int, default=64)
    parser.add_argument("--ttl", type=int, default=200)
    parser.add_argument("--scout-emission-rate", type=float, default=100.0)
    parser.add_argument(
        "--no-useful-scouts-only",
        action="store_true",
        help="disable the useful-scout filter (enabled by default)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="only run the first N hex milestones (0 = all)",
    )
    args = parser.parse_args()
    useful_scouts_only = not args.no_useful_scouts_only

    subprocess.run(["make", "-C", str(ROOT / "cpp")], check=True)

    _, vertex_count, hex_count = build_hexagon_graph(HEXAGON_N)
    milestones = hexagon_vertex_milestones(HEXAGON_N)
    if args.limit > 0:
        milestones = milestones[: args.limit]

    matplotlib.rcParams.update(
        {
            "font.size": 18,
            "axes.titlesize": 22,
            "axes.labelsize": 20,
            "xtick.labelsize": 18,
            "ytick.labelsize": 18,
            "legend.fontsize": 18,
            "lines.linewidth": 2.0,
        }
    )

    plt.ion()
    fig, ax = plt.subplots(figsize=(9, 5.5))
    (plot_line,) = ax.plot([], [], marker="o", markersize=5, color="C0")
    status_text = ax.text(
        0.02,
        0.98,
        "",
        transform=ax.transAxes,
        va="top",
        ha="left",
        fontsize=14,
        bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "none"},
    )

    x_major = pick_x_major_ticks(vertex_count)
    ax.set_xlabel("Vertices")
    # ax.set_ylabel("Convergence time")
    ax.set_xlim(0, vertex_count + 4)
    ax.set_xticks(x_major)
    ax.set_xticks(milestones, minor=True)
    ax.tick_params(axis="x", which="major", length=8)
    ax.tick_params(axis="x", which="minor", length=4)
    ax.grid(True, which="major", axis="both", alpha=0.25)
    ax.grid(True, which="minor", axis="x", alpha=0.15)
    configure_y_axis(ax)

    fig.canvas.draw()
    fig.canvas.flush_events()

    x: list[int] = []
    y: list[float] = []

    for hex_idx, vertices in enumerate(tqdm.tqdm(milestones, desc="hexagons"), start=1):
        status_text.set_text(f"hex {hex_idx}/{hex_count}\n{vertices} vertices\nrunning…")
        fig.canvas.draw_idle()
        fig.canvas.flush_events()

        seconds = get_hexagon_scalability_data_point(
            vertices,
            args.src_node,
            useful_scouts_only,
            args.block_chunks,
            args.ttl,
            args.scout_emission_rate,
        )
        minutes = seconds / 60.0

        x.append(vertices)
        y.append(seconds)
        plot_line.set_data(x, y)

        status_text.set_text(
            f"hex {hex_idx}/{hex_count}\n{vertices} vertices\n{minutes:.1f} min"
        )
        fig.canvas.draw()
        fig.canvas.flush_events()

    plt.ioff()
    os.makedirs(ROOT / "figs", exist_ok=True)
    fig.savefig(ROOT / "figs" / "hexagon-scalability.pdf", bbox_inches="tight")
    plt.show()


if __name__ == "__main__":
    main()
