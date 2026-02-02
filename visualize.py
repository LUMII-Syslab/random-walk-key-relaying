"""
Visualization utilities for random walk key relaying throughput analysis.
"""

from __future__ import annotations

import math
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

import signal

signal.signal(signal.SIGINT, signal.SIG_DFL)

def _norm_cdf(x: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return np.full_like(x, np.nan, dtype=float)
    z = (x - mu) / (sigma * math.sqrt(2.0))
    # vectorized erf via np.vectorize over math.erf (keeps deps minimal)
    erfv = np.vectorize(math.erf)
    return 0.5 * (1.0 + erfv(z))


def _norm_pdf(x: np.ndarray, mu: float, sigma: float) -> np.ndarray:
    if sigma <= 0:
        return np.full_like(x, np.nan, dtype=float)
    z = (x - mu) / sigma
    return (1.0 / (sigma * math.sqrt(2.0 * math.pi))) * np.exp(-0.5 * z * z)


def draw_plots(
    config: dict[str, Any],
    summary: dict[str, Any],
    sliding: dict[str, Any],
    non_overlapping: dict[str, Any],
    log_domain: dict[str, Any],
    output_path: str = "throughput.png",
    show: bool = True,
) -> None:
    if not summary.get("has_enough_arrivals", False):
        return

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    ax1 = axes[0, 0]  # time series
    ax2 = axes[0, 1]  # linear histogram
    ax3 = axes[1, 0]  # log histogram
    ax4 = axes[1, 1]  # P-P plot for log domain

    mean_color = "tab:orange"
    median_color = "tab:green"

    # Left: time series (sliding window)
    if len(sliding["values"]):
        ax1.plot(sliding["times"], sliding["values"], linewidth=0.8, alpha=0.7)
        ax1.axhline(
            y=float(np.mean(sliding["values"])),
            linestyle="--",
            linewidth=1.5,
            color=mean_color,
            label=f"Mean: {np.mean(sliding['values']):.3f}",
        )
        ax1.axhline(
            y=float(np.median(sliding["values"])),
            linestyle="-.",
            linewidth=1.5,
            color=median_color,
            label=f"Median: {np.median(sliding['values']):.3f}",
        )
        ax1.set_title(f"Sliding-window Throughput: {config['S']} -> {config['T']}")
    else:
        ax1.set_title("Sliding-window Throughput (no samples)")
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Throughput (bits/s)")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper right")

    # Top-right: histogram of NON-overlapping window throughput (quantized -> use step bins)
    thr_bins = non_overlapping["thr_bins"]
    if len(thr_bins):
        thr_step = non_overlapping["thr_step"]
        bin_min = np.floor(thr_bins.min() / thr_step) * thr_step
        bin_max = np.ceil(thr_bins.max() / thr_step) * thr_step
        bins = np.arange(bin_min - 0.5 * thr_step, bin_max + 1.5 * thr_step, thr_step)

        ax2.hist(thr_bins, bins=bins, edgecolor="black", alpha=0.7)
        ax2.axvline(
            x=non_overlapping["mean_thr"],
            linestyle="--",
            linewidth=1.5,
            color=mean_color,
            label=f"Mean: {non_overlapping['mean_thr']:.3f}",
        )
        ax2.axvline(
            x=non_overlapping["median_thr"],
            linestyle="-.",
            linewidth=1.5,
            color=median_color,
            label=f"Median: {non_overlapping['median_thr']:.3f}",
        )
        ax2.axvline(
            x=non_overlapping["p05"],
            linestyle=":",
            linewidth=1.2,
            label=f"P05/P95: {non_overlapping['p05']:.3f}/{non_overlapping['p95']:.3f}",
        )
        ax2.axvline(x=non_overlapping["p95"], linestyle=":", linewidth=1.2)
        ax2.set_title(
            f"Non-overlapping Window Throughput (bin={non_overlapping['bin_w']}s)"
        )
        ax2.set_xlabel("Throughput (bits/s)")
        ax2.set_ylabel("Frequency")
        ax2.grid(True, alpha=0.3, axis="y")
        ax2.legend(loc="upper right")
    else:
        ax2.set_title("Histogram (no samples)")
        ax2.set_axis_off()

    # Bottom-left: histogram of log(throughput) for thr>0 with fitted normal overlay
    if len(log_domain["log_thr"]):
        ax3.hist(log_domain["log_thr"], bins="auto", density=True, edgecolor="black", alpha=0.7)
        xs = np.linspace(log_domain["log_thr"].min(), log_domain["log_thr"].max(), 200)
        ax3.plot(
            xs,
            _norm_pdf(xs, log_domain["log_mu"], log_domain["log_sigma"]),
            linewidth=1.5,
            label=f"Normal fit mu={log_domain['log_mu']:.3f}, sigma={log_domain['log_sigma']:.3f}",
        )
        ax3.set_title("log(Throughput) density (thr>0)")
        ax3.set_xlabel("log(bits/s)")
        ax3.set_ylabel("Density")
        ax3.grid(True, alpha=0.3, axis="y")
        ax3.legend(loc="upper right")
    else:
        ax3.set_title("log(Throughput) (no positive samples)")
        ax3.set_axis_off()

    # Bottom-right: P-P plot of log(throughput) vs fitted normal
    if len(log_domain["log_thr"]) >= 10 and log_domain["log_sigma"] > 0:
        x_sorted = np.sort(log_domain["log_thr"])
        n = len(x_sorted)
        emp = (np.arange(1, n + 1) - 0.5) / n
        theo = _norm_cdf(x_sorted, log_domain["log_mu"], log_domain["log_sigma"])
        ax4.plot(theo, emp, ".", alpha=0.6)
        ax4.plot([0, 1], [0, 1], linestyle="--", linewidth=1.2)
        ax4.set_title("P-P plot: log(thr) vs fitted normal")
        ax4.set_xlabel("Theoretical CDF")
        ax4.set_ylabel("Empirical CDF")
        ax4.grid(True, alpha=0.3)
    else:
        ax4.set_title("P-P plot (insufficient log samples)")
        ax4.set_axis_off()

    plt.suptitle(
        f"Random Walk Key Relay (burn-in={config['BURN_IN']}s, sim={config['SIM_DURATION']}s)",
        fontsize=12,
    )
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    if show:
        plt.show()
    print(f"\nPlot saved to {output_path}")

