import matplotlib
import matplotlib.pyplot as plt
import os
from joblib import Memory
import subprocess
import re
import numpy as np
import tqdm
import signal
import sys

def signal_handler(sig, frame):
    plt.ioff()
    plt.show()
    sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)

location = os.path.join(os.path.expanduser("~"), ".cache", "random-walk-relaying")
memory = Memory(location=location, verbose=0)

@memory.cache
def get_batch_sensitivity_data_point(src_node: str, block_chunks: int) -> float:
    result = subprocess.run(
        [
            "./build/scouted",
            "-S", src_node,
            "--useful-scouts-only",
            "--block-chunks", str(block_chunks),
        ],
        capture_output=True,
        text=True,
        cwd="cpp",
    )
    return float(re.search(r"Halted at ([\d\.]+) seconds", result.stdout).group(1))

if __name__ == "__main__":
    subprocess.run(["make", "-C", "cpp"])

    src_nodes = ["MAR", "PAR", "NIC", "RIG"]
    batch_sizes = np.unique(np.geomspace(8, 64, 24).astype(int))
    line_styles = ["-", "--", "-.", ":"]
    markers = ["o", "s", "^", "D"]

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
    fig, ax = plt.subplots(figsize=(8, 5))
    plot_lines = [
        ax.plot(
            [], [],
            label=src,
            linestyle=ls,
            marker=mk,
            markersize=5,
        )[0]
        for src, ls, mk in zip(src_nodes, line_styles, markers)
    ]
    ax.set_xlabel("Chunk batch size")
    y_major_min = [16, 32, 48]
    y_minor_min = [8, 24, 40, 56]
    ax.set_yticks([m * 60 for m in y_major_min])
    ax.set_yticklabels([f"{m} min" for m in y_major_min])
    ax.set_yticks([m * 60 for m in y_minor_min], minor=True)
    ax.set_ylim(y_minor_min[0] * 60, y_minor_min[-1] * 60)
    ax.tick_params(axis="y", which="major", length=8)
    ax.tick_params(axis="y", which="minor", length=4)
    ax.legend()
    fig.canvas.draw()
    fig.canvas.flush_events()

    for plot_line, src_node in zip(plot_lines, tqdm.tqdm(src_nodes)):
        x = []
        y = []
        for block_chunks in tqdm.tqdm(batch_sizes, leave=False):
            x.append(block_chunks)
            convergence_time = get_batch_sensitivity_data_point(src_node, block_chunks)
            y.append(convergence_time)
            plot_line.set_data(x, y)
            ax.relim()
            ax.autoscale_view(scalex=True, scaley=False)
            fig.canvas.draw()
            fig.canvas.flush_events()

    plt.ioff()

    os.makedirs("figs", exist_ok=True)
    fig.savefig("figs/batch-sensitivity.pdf", bbox_inches="tight")

    plt.show()
