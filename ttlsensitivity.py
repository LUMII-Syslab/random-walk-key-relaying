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
def getTtlSensitivityDataPoint(ttl: int, scout_emission_rate: int) -> int:
    result = subprocess.run(["./build/scouted", "-S", "MAR", "--useful-scouts-only", "--scout-emission-rate", str(scout_emission_rate), "--ttl", str(ttl)], capture_output=True, text=True, cwd="cpp")
    return float(re.search(r'Halted at ([\d\.]+) seconds', result.stdout).group(1))

if __name__ == "__main__":
    subprocess.run(["make", "-C", "cpp"])

    scout_emission_rates = [8, 16, 128]
    ttls = np.unique(np.geomspace(50, 500, 80).astype(int))
    line_styles = ["-", "--", "-."]
    markers = ["o", "s", "^"]

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

    # plt.ion()
    fig, ax = plt.subplots(figsize=(8, 5))
    plot_lines = [
        ax.plot(
            [], [],
            label=f"Emit {rate} scouts/s",
            linestyle=ls,
            marker=mk,
            markersize=5,
        )[0]
        for rate, ls, mk in zip(scout_emission_rates, line_styles, markers)
    ]
    ax.set_xlabel("Max TTL parameter")
    # ax.set_ylabel("Convergence time")
    y_major_min = [16, 32, 48, 64, 80]
    y_minor_min = [24, 40, 56, 72, 88]  # majors at 16, 32, 64 — no overlap
    ax.set_yticks([m * 60 for m in y_major_min])
    ax.set_yticklabels([f"{m} min" for m in y_major_min])
    ax.set_yticks([m * 60 for m in y_minor_min], minor=True)
    ax.set_ylim(y_major_min[0] * 60, y_major_min[-1] * 60)
    ax.tick_params(axis="y", which="major", length=8)
    ax.tick_params(axis="y", which="minor", length=4)
    ax.legend()
    fig.canvas.draw()
    fig.canvas.flush_events()

    for plot_line, scout_emission_rate in zip(plot_lines, tqdm.tqdm(scout_emission_rates)):
        x = []
        y = []
        for ttl in tqdm.tqdm(ttls, leave=False):
            x.append(ttl)
            convergence_time = getTtlSensitivityDataPoint(ttl, scout_emission_rate)
            y.append(convergence_time)
            plot_line.set_data(x, y)
            ax.relim()
            ax.autoscale_view(scalex=True, scaley=False)
            fig.canvas.draw()
            fig.canvas.flush_events()

    plt.ioff()

    os.makedirs("figs", exist_ok=True)
    fig.savefig("figs/ttl-sensitivity.pdf", bbox_inches="tight")

    plt.show()

