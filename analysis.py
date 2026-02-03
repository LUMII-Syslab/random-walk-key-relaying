"""
Post-processing for random walk key relaying throughput simulations.
Computes statistics and prepares data for visualization.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from typing import Any

import matplotlib
import numpy as np

# Source - https://stackoverflow.com/a/6441839 \cite{retegran2011matplotlibfontsize}
# Posted by Marius Retegan
# Retrieved 2026-02-02, License - CC BY-SA 3.0
matplotlib.rcParams.update({"font.size": 12})


@dataclass(frozen=True)
class Summary:
    total_keys: int
    total_bits: int
    has_enough_arrivals: bool


@dataclass(frozen=True)
class ArrivalMetrics:
    mean_iat: float
    cv_iat: float
    rate_keys: float
    rate_bits: float


@dataclass(frozen=True)
class NonOverlappingThroughput:
    bin_w: float
    thr_bins: np.ndarray
    thr_step: float
    unique_thr: np.ndarray
    zero_windows: int
    frac_zero: float
    median_thr: float
    p05: float
    p95: float
    iqr: float
    mad: float
    mean_thr: float
    std_thr: float
    skew_thr: float
    kurt_thr: float
    fano: float
    jb_lin: float
    p_lin: float


@dataclass(frozen=True)
class SlidingWindowSeries:
    times: np.ndarray
    values: np.ndarray
    lag1: float
    ess: float


@dataclass(frozen=True)
class LogDomainMetrics:
    log_thr: np.ndarray
    log_mu: float
    log_sigma: float
    jb_log: float
    p_log: float


def _skewness(x: np.ndarray) -> float:
    if len(x) < 3:
        return float("nan")
    m = x.mean()
    s = x.std(ddof=0)
    if s == 0:
        return 0.0
    return float(np.mean(((x - m) / s) ** 3))


def _excess_kurtosis(x: np.ndarray) -> float:
    if len(x) < 4:
        return float("nan")
    m = x.mean()
    s = x.std(ddof=0)
    if s == 0:
        return 0.0
    return float(np.mean(((x - m) / s) ** 4) - 3.0)


def _lag1_autocorr(x: np.ndarray) -> float:
    if len(x) < 2:
        return float("nan")
    x0 = x[:-1]
    x1 = x[1:]
    if x0.std(ddof=0) == 0 or x1.std(ddof=0) == 0:
        return 0.0
    return float(np.corrcoef(x0, x1)[0, 1])


def _jarque_bera(x: np.ndarray) -> tuple[float, float]:
    """
    Jarque-Bera normality test statistic and (approx) p-value.
    For large n, JB ~ Chi^2(df=2). For df=2, survival function is exp(-JB/2).
    """
    n = len(x)
    if n < 4:
        return float("nan"), float("nan")
    s = _skewness(x)
    k = _excess_kurtosis(x)  # excess kurtosis
    jb = (n / 6.0) * (s * s + 0.25 * k * k)
    p = float(np.exp(-jb / 2.0))  # df=2
    return float(jb), p


class Analyzer:
    def __init__(self, config: dict[str, Any]):
        self.config = config

    def compute_summary(self, arrival_times: list[float]) -> Summary:
        total_keys = len(arrival_times)
        total_bits = total_keys * self.config["KEY_SIZE"]
        return Summary(
            total_keys=total_keys,
            total_bits=total_bits,
            has_enough_arrivals=total_keys >= 2,
        )

    def compute_arrival_metrics(
        self, arrival_times: list[float], summary: Summary
    ) -> ArrivalMetrics:
        if summary.total_keys < 2:
            return ArrivalMetrics(
                mean_iat=float("nan"),
                cv_iat=float("nan"),
                rate_keys=0.0,
                rate_bits=0.0,
            )
        all_arr = np.array(arrival_times, dtype=float)
        inter = np.diff(all_arr)
        mean_iat = float(np.mean(inter))
        cv_iat = (
            float(np.std(inter, ddof=0) / mean_iat) if mean_iat > 0 else float("nan")
        )
        rate_keys = float(summary.total_keys / self.config["SIM_DURATION"])
        rate_bits = float(summary.total_bits / self.config["SIM_DURATION"])
        return ArrivalMetrics(
            mean_iat=mean_iat,
            cv_iat=cv_iat,
            rate_keys=rate_keys,
            rate_bits=rate_bits,
        )

    def compute_non_overlapping_throughput(
        self, arrival_times: list[float]
    ) -> NonOverlappingThroughput:
        if len(arrival_times) < 2:
            return NonOverlappingThroughput(
                bin_w=float(self.config["WINDOW_SIZE"]),
                thr_bins=np.array([], dtype=float),
                thr_step=self.config["KEY_SIZE"] / float(self.config["WINDOW_SIZE"]),
                unique_thr=np.array([], dtype=float),
                zero_windows=0,
                frac_zero=float("nan"),
                median_thr=float("nan"),
                p05=float("nan"),
                p95=float("nan"),
                iqr=float("nan"),
                mad=float("nan"),
                mean_thr=float("nan"),
                std_thr=float("nan"),
                skew_thr=float("nan"),
                kurt_thr=float("nan"),
                fano=float("nan"),
                jb_lin=float("nan"),
                p_lin=float("nan"),
            )

        all_arr = np.array(arrival_times, dtype=float)
        bin_w = float(self.config["WINDOW_SIZE"])
        edges_bins = np.arange(0.0, self.config["SIM_DURATION"] + bin_w, bin_w)
        counts, _ = np.histogram(all_arr, bins=edges_bins)
        bin_centers = edges_bins[:-1] + bin_w / 2.0
        mask = bin_centers >= self.config["BURN_IN"]
        counts_ss = counts[mask]
        thr_bins = counts_ss * self.config["KEY_SIZE"] / bin_w  # bits/s
        thr_step = self.config["KEY_SIZE"] / bin_w
        unique_thr = np.unique(thr_bins)
        zero_windows = int(np.sum(counts_ss == 0))
        frac_zero = zero_windows / len(counts_ss) if len(counts_ss) else float("nan")

        def q(a: np.ndarray, p: float) -> float:
            return float(np.quantile(a, p)) if len(a) else float("nan")

        median_thr = q(thr_bins, 0.5)
        p05, p95 = q(thr_bins, 0.05), q(thr_bins, 0.95)
        q25, q75 = q(thr_bins, 0.25), q(thr_bins, 0.75)
        iqr = q75 - q25
        mad = (
            float(np.median(np.abs(thr_bins - np.median(thr_bins))))
            if len(thr_bins)
            else float("nan")
        )

        mean_thr = float(np.mean(thr_bins)) if len(thr_bins) else float("nan")
        std_thr = float(np.std(thr_bins, ddof=0)) if len(thr_bins) else float("nan")
        skew_thr = _skewness(thr_bins) if len(thr_bins) else float("nan")
        kurt_thr = _excess_kurtosis(thr_bins) if len(thr_bins) else float("nan")

        mean_c = float(np.mean(counts_ss)) if len(counts_ss) else float("nan")
        var_c = float(np.var(counts_ss, ddof=0)) if len(counts_ss) else float("nan")
        fano = (var_c / mean_c) if mean_c > 0 else float("nan")

        jb_lin, p_lin = (
            _jarque_bera(thr_bins) if len(thr_bins) else (float("nan"), float("nan"))
        )

        return NonOverlappingThroughput(
            bin_w=bin_w,
            thr_bins=thr_bins,
            thr_step=thr_step,
            unique_thr=unique_thr,
            zero_windows=zero_windows,
            frac_zero=frac_zero,
            median_thr=median_thr,
            p05=p05,
            p95=p95,
            iqr=iqr,
            mad=mad,
            mean_thr=mean_thr,
            std_thr=std_thr,
            skew_thr=skew_thr,
            kurt_thr=kurt_thr,
            fano=fano,
            jb_lin=jb_lin,
            p_lin=p_lin,
        )

    def compute_sliding_window_metrics(
        self, arrival_times: list[float]
    ) -> SlidingWindowSeries:
        if not arrival_times:
            return SlidingWindowSeries(
                times=np.array([], dtype=float),
                values=np.array([], dtype=float),
                lag1=float("nan"),
                ess=float("nan"),
            )

        arrivals = np.array(arrival_times, dtype=float)
        tick_interval = float(self.config["TICK_INTERVAL"])
        window_size = float(self.config["WINDOW_SIZE"])
        sim_duration = float(self.config["SIM_DURATION"])
        burn_in = float(self.config["BURN_IN"])
        min_keys_in_window = int(self.config["MIN_KEYS_IN_WINDOW"])
        key_size = float(self.config["KEY_SIZE"])

        tick_times = np.arange(tick_interval, sim_duration + 1e-9, tick_interval)
        series_times = []
        series_values = []

        left = 0
        right = 0
        n = len(arrivals)
        for t in tick_times:
            while right < n and arrivals[right] <= t:
                right += 1
            cutoff = t - window_size
            while left < right and arrivals[left] < cutoff:
                left += 1
            keys_in_window = right - left
            throughput = (keys_in_window * key_size) / window_size
            if t >= burn_in and keys_in_window >= min_keys_in_window:
                series_times.append(t)
                series_values.append(throughput)

        if series_values:
            sw = np.array(series_values, dtype=float)
            sw_lag1 = _lag1_autocorr(sw)
            ess = (
                float(len(sw) * (1 - sw_lag1) / (1 + sw_lag1))
                if abs(sw_lag1) < 0.999
                else float("nan")
            )
        else:
            sw = np.array([], dtype=float)
            sw_lag1, ess = float("nan"), float("nan")

        return SlidingWindowSeries(
            times=np.array(series_times, dtype=float),
            values=sw,
            lag1=sw_lag1,
            ess=ess,
        )

    def compute_log_domain_metrics(self, thr_bins: np.ndarray) -> LogDomainMetrics:
        thr_pos = thr_bins[thr_bins > 0]
        log_thr = np.log(thr_pos) if len(thr_pos) else np.array([], dtype=float)
        log_mu = float(np.mean(log_thr)) if len(log_thr) else float("nan")
        log_sigma = float(np.std(log_thr, ddof=0)) if len(log_thr) else float("nan")
        jb_log, p_log = (
            _jarque_bera(log_thr) if len(log_thr) else (float("nan"), float("nan"))
        )
        return LogDomainMetrics(
            log_thr=log_thr,
            log_mu=log_mu,
            log_sigma=log_sigma,
            jb_log=jb_log,
            p_log=p_log,
        )

    def print_summary(
        self,
        summary: Summary,
        arrival: ArrivalMetrics,
        non_overlapping: NonOverlappingThroughput,
        sliding: SlidingWindowSeries,
        log_domain: LogDomainMetrics,
        summary_path: str | None = None,
    ) -> None:
        config = self.config

        output = None
        if summary_path:
            os.makedirs(os.path.dirname(summary_path) or ".", exist_ok=True)
            output = open(summary_path, "w", encoding="utf-8")

        def _p(text: str = "") -> None:
            print(text, file=output)

        _p("\n=== Summary ===")
        _p("\n--- Configuration ---")
        _p(f"KEY_SIZE: {config['KEY_SIZE']} bits")
        _p(f"NODE_BUFF_KEYS: {config['NODE_BUFF_KEYS']}")
        _p(f"LINK_BUFF_BITS: {config['LINK_BUFF_BITS']} bits")
        _p(f"LINKS_EMPTY_AT_START: {config['LINKS_EMPTY_AT_START']}")
        _p(f"QKD_SKR: {config['QKD_SKR']} bits/s")
        _p(f"LATENCY: {config['LATENCY']} s")
        _p(f"TICK_INTERVAL: {config['TICK_INTERVAL']} s")
        _p(f"WINDOW_SIZE: {config['WINDOW_SIZE']} s")
        _p(f"SIM_DURATION: {config['SIM_DURATION']} s")
        _p(f"HIST_BIN_WIDTH: {config['HIST_BIN_WIDTH']} bits/s")
        _p(f"MIN_KEYS_IN_WINDOW: {config['MIN_KEYS_IN_WINDOW']}")
        _p(f"BURN_IN: {config['BURN_IN']} s")
        _p(f"S: {config['S']} | T: {config['T']}")
        _p(f"Nodes: {config['nodes_count']} | Edges: {config['edges_count']}")
        _p(
            f"Delivered keys: {summary.total_keys} | Delivered bits: {summary.total_bits} | "
            f"Sim duration: {config['SIM_DURATION']}s | Burn-in: {config['BURN_IN']}s"
        )

        if not summary.has_enough_arrivals:
            _p("Not enough arrivals for meaningful statistics.")
            if output:
                output.close()
            return

        _p("\n--- Arrival process ---")
        _p(
            f"Avg delivery rate: {arrival.rate_keys:.6f} keys/s | {arrival.rate_bits:.6f} bits/s"
        )
        _p(
            f"Mean inter-arrival: {arrival.mean_iat:.6f}s | CV(inter-arrival): {arrival.cv_iat:.3f} "
            f"(Poisson would be ~1.0)"
        )

        _p("\n--- Non-overlapping window throughput (preferred for distribution) ---")
        _p(
            f"Samples: {len(non_overlapping.thr_bins)} windows of {non_overlapping.bin_w}s "
            f"(post burn-in)"
        )
        _p(
            f"Quantization step: {non_overlapping.thr_step:.6f} bits/s | "
            f"Unique throughput values: {len(non_overlapping.unique_thr)}"
        )
        _p(
            f"Zero-count windows: {non_overlapping.zero_windows}/{len(non_overlapping.thr_bins)} = "
            f"{non_overlapping.frac_zero:.3f} (log() drops these)"
        )
        _p(
            f"Mean:   {non_overlapping.mean_thr:.6f} | Std: {non_overlapping.std_thr:.6f}  "
            f"(std shown for reference)"
        )
        _p(
            f"Median: {non_overlapping.median_thr:.6f} | IQR: {non_overlapping.iqr:.6f} | "
            f"MAD: {non_overlapping.mad:.6f}"
        )
        _p(f"P05:    {non_overlapping.p05:.6f} | P95: {non_overlapping.p95:.6f}")
        _p(
            f"Skew:   {non_overlapping.skew_thr:.3f} | Excess kurtosis: "
            f"{non_overlapping.kurt_thr:.3f}"
        )
        _p(
            f"Fano factor on window counts Var/Mean: {non_overlapping.fano:.3f}  "
            f"(Poisson-ish ~1, bursty >1)"
        )
        _p(
            f"JB normality (linear thr): JB={non_overlapping.jb_lin:.3f}, "
            f"p≈{non_overlapping.p_lin:.3g} (small p => not normal)"
        )
        _p(
            f"JB normality (log thr>0): JB={log_domain.jb_log:.3f}, "
            f"p≈{log_domain.p_log:.3g} (small p => not log-normal)"
        )

        _p("\n--- Sliding-window throughput series (correlated diagnostics) ---")
        if len(sliding.values):
            _p(f"Recorded points: {len(sliding.values)} (post burn-in)")
            _p(f"Lag-1 autocorr: {sliding.lag1:.3f}  (expect high due to overlap)")
            _p(f"Crude ESS (AR(1) approx): {sliding.ess:.1f}")
        else:
            _p("No sliding-window points recorded (check MIN_KEYS_IN_WINDOW / burn-in).")

        if output:
            output.close()


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


def plot_sliding_window(
    ax,
    sliding: SlidingWindowSeries,
    config: dict[str, Any],
):
    to_kbits = 1.0 / 1000.0
    mean_color = "tab:orange"
    median_color = "tab:red"
    if len(sliding.values):
        values_kbits = sliding.values * to_kbits
        ax.plot(sliding.times, values_kbits)
        ax.axhline(
            y=float(np.mean(values_kbits)),
            linestyle="--",
            linewidth=1.5,
            color=mean_color,
            label=f"Mean: {np.mean(values_kbits):.3f}",
        )
        ax.axhline(
            y=float(np.median(values_kbits)),
            linestyle="-.",
            linewidth=1.5,
            color=median_color,
            label=f"Median: {np.median(values_kbits):.3f}",
        )
        # ax.set_title(f"Sliding-window Throughput: ")
        ax.set_title(f"Throughput time series (sliding window - {config['WINDOW_SIZE']}s)")
    else:
        ax.set_title("Sliding-window Throughput (no samples)")
    ax.set_xlabel("Time [s]")
    ax.set_ylabel(
        f"Throughput [kbits/s] ({config['S']} → {config['T']}, {config['VARIANT']})"
    )
    ax.grid(True, alpha=0.3)
    ax.legend(loc="upper right")
    return ax


def plot_non_overlapping_histogram(
    ax, non_overlapping: NonOverlappingThroughput, config: dict[str, Any]
):
    to_kbits = 1.0 / 1000.0
    mean_color = "tab:orange"
    median_color = "tab:red"
    if len(non_overlapping.thr_bins):
        thr_bins_plot = non_overlapping.thr_bins[
            non_overlapping.thr_bins > 0
        ]
        # if not np.isnan(non_overlapping.p05):
        #     thr_bins_plot = thr_bins_plot[thr_bins_plot >= non_overlapping.p05]
        if not len(thr_bins_plot):
            ax.set_title("Histogram (no positive samples)")
            ax.set_axis_off()
            return ax

        thr_bins_plot_kbits = thr_bins_plot * to_kbits
        thr_step_kbits = non_overlapping.thr_step * to_kbits
        bin_min = np.floor(thr_bins_plot_kbits.min() / thr_step_kbits) * thr_step_kbits
        bin_max = np.ceil(thr_bins_plot_kbits.max() / thr_step_kbits) * thr_step_kbits
        bin_start = max(thr_step_kbits, bin_min - 0.5 * thr_step_kbits)
        bins = np.arange(bin_start, bin_max + 1.5 * thr_step_kbits, thr_step_kbits)

        weights = np.full_like(thr_bins_plot_kbits, 100.0 / len(thr_bins_plot_kbits))
        ax.hist(
            thr_bins_plot_kbits,
            bins=bins,
            edgecolor="black",
            alpha=0.7,
            weights=weights,
        )
        # Mean/median markers intentionally omitted for this histogram.
        ax.axvline(
            x=non_overlapping.p05 * to_kbits,
            linestyle=":",
            linewidth=2,
            label=(
                "P05/P95: "
                f"{non_overlapping.p05 * to_kbits:.3f}/"
                f"{non_overlapping.p95 * to_kbits:.3f}"
            ),
            color="tab:purple"
        )
        ax.axvline(x=non_overlapping.p95 * to_kbits, linestyle=":", linewidth=2, color="tab:purple")
        ax.set_title(
            # f"Non-overlapping Window Throughput (bin={non_overlapping.bin_w}s)"
            f"Freq distribution (non-overlapping window - {non_overlapping.bin_w}s)"
        )
        ax.set_xlabel(
            f"Throughput [kbits/s] ({config['S']} → {config['T']}, {config['VARIANT']})"
        )
        ax.set_ylabel("Frequency [%]")
        _, ymax = ax.get_ylim()
        ax.set_yticks(np.arange(0, ymax + 5, 5))
        ax.grid(True, alpha=0.3, axis="y")
        ax.legend(loc="upper right")
    else:
        ax.set_title("Histogram (no samples)")
        ax.set_axis_off()
    return ax


def plot_log_histogram(ax, log_domain: LogDomainMetrics):
    if len(log_domain.log_thr):
        ax.hist(log_domain.log_thr, bins="auto", density=True, edgecolor="black", alpha=0.7)
        xs = np.linspace(log_domain.log_thr.min(), log_domain.log_thr.max(), 200)
        ax.plot(
            xs,
            _norm_pdf(xs, log_domain.log_mu, log_domain.log_sigma),
            linewidth=1.5,
            label=f"Normal fit mu={log_domain.log_mu:.3f}, sigma={log_domain.log_sigma:.3f}",
        )
        ax.set_title("log(Throughput) density (thr>0)")
        ax.set_xlabel("log(bits/s)")
        ax.set_ylabel("Density")
        ax.grid(True, alpha=0.3, axis="y")
        ax.legend(loc="upper right")
    else:
        ax.set_title("log(Throughput) (no positive samples)")
        ax.set_axis_off()
    return ax


def plot_pp(ax, log_domain: LogDomainMetrics):
    if len(log_domain.log_thr) >= 10 and log_domain.log_sigma > 0:
        x_sorted = np.sort(log_domain.log_thr)
        n = len(x_sorted)
        emp = (np.arange(1, n + 1) - 0.5) / n
        theo = _norm_cdf(x_sorted, log_domain.log_mu, log_domain.log_sigma)
        ax.plot(theo, emp, ".", alpha=0.6)
        ax.plot([0, 1], [0, 1], linestyle="--", linewidth=1.2)
        ax.set_title("P-P plot: log(thr) vs fitted normal")
        ax.set_xlabel("Theoretical CDF")
        ax.set_ylabel("Empirical CDF")
        ax.grid(True, alpha=0.3)
    else:
        ax.set_title("P-P plot (insufficient log samples)")
        ax.set_axis_off()
    return ax

