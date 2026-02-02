"""
Post-processing for random walk key relaying throughput simulations.
Computes statistics and prepares data for visualization.
"""

from __future__ import annotations

from typing import Any

import numpy as np


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


def compute_summary(
    arrival_times: list[float], config: dict[str, Any]
) -> dict[str, Any]:
    total_keys = len(arrival_times)
    total_bits = total_keys * config["KEY_SIZE"]
    return {
        "total_keys": total_keys,
        "total_bits": total_bits,
        "has_enough_arrivals": total_keys >= 2,
    }


def compute_arrival_metrics(
    arrival_times: list[float], summary: dict[str, Any], config: dict[str, Any]
) -> dict[str, Any]:
    if summary["total_keys"] < 2:
        return {"mean_iat": float("nan"), "cv_iat": float("nan"), "rate_keys": 0.0, "rate_bits": 0.0}
    all_arr = np.array(arrival_times, dtype=float)
    inter = np.diff(all_arr)
    mean_iat = float(np.mean(inter))
    cv_iat = float(np.std(inter, ddof=0) / mean_iat) if mean_iat > 0 else float("nan")
    rate_keys = float(summary["total_keys"] / config["SIM_DURATION"])
    rate_bits = float(summary["total_bits"] / config["SIM_DURATION"])
    return {
        "mean_iat": mean_iat,
        "cv_iat": cv_iat,
        "rate_keys": rate_keys,
        "rate_bits": rate_bits,
    }


def compute_non_overlapping_throughput(
    arrival_times: list[float], config: dict[str, Any]
) -> dict[str, Any]:
    if len(arrival_times) < 2:
        return {
            "bin_w": float(config["WINDOW_SIZE"]),
            "thr_bins": np.array([], dtype=float),
            "thr_step": config["KEY_SIZE"] / float(config["WINDOW_SIZE"]),
            "unique_thr": np.array([], dtype=float),
            "zero_windows": 0,
            "frac_zero": float("nan"),
            "median_thr": float("nan"),
            "p05": float("nan"),
            "p95": float("nan"),
            "iqr": float("nan"),
            "mad": float("nan"),
            "mean_thr": float("nan"),
            "std_thr": float("nan"),
            "skew_thr": float("nan"),
            "kurt_thr": float("nan"),
            "fano": float("nan"),
            "jb_lin": float("nan"),
            "p_lin": float("nan"),
        }

    all_arr = np.array(arrival_times, dtype=float)
    bin_w = float(config["WINDOW_SIZE"])
    edges_bins = np.arange(0.0, config["SIM_DURATION"] + bin_w, bin_w)
    counts, _ = np.histogram(all_arr, bins=edges_bins)
    bin_centers = edges_bins[:-1] + bin_w / 2.0
    mask = bin_centers >= config["BURN_IN"]
    counts_ss = counts[mask]
    thr_bins = counts_ss * config["KEY_SIZE"] / bin_w  # bits/s
    thr_step = config["KEY_SIZE"] / bin_w
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

    jb_lin, p_lin = _jarque_bera(thr_bins) if len(thr_bins) else (float("nan"), float("nan"))

    return {
        "bin_w": bin_w,
        "thr_bins": thr_bins,
        "thr_step": thr_step,
        "unique_thr": unique_thr,
        "zero_windows": zero_windows,
        "frac_zero": frac_zero,
        "median_thr": median_thr,
        "p05": p05,
        "p95": p95,
        "iqr": iqr,
        "mad": mad,
        "mean_thr": mean_thr,
        "std_thr": std_thr,
        "skew_thr": skew_thr,
        "kurt_thr": kurt_thr,
        "fano": fano,
        "jb_lin": jb_lin,
        "p_lin": p_lin,
    }


def compute_sliding_window_metrics(
    arrival_times: list[float], config: dict[str, Any]
) -> dict[str, Any]:
    if not arrival_times:
        return {
            "times": np.array([], dtype=float),
            "values": np.array([], dtype=float),
            "lag1": float("nan"),
            "ess": float("nan"),
        }

    arrivals = np.array(arrival_times, dtype=float)
    tick_interval = float(config["TICK_INTERVAL"])
    window_size = float(config["WINDOW_SIZE"])
    sim_duration = float(config["SIM_DURATION"])
    burn_in = float(config["BURN_IN"])
    min_keys_in_window = int(config["MIN_KEYS_IN_WINDOW"])
    key_size = float(config["KEY_SIZE"])

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

    return {
        "times": np.array(series_times, dtype=float),
        "values": sw,
        "lag1": sw_lag1,
        "ess": ess,
    }


def compute_log_domain_metrics(thr_bins: np.ndarray) -> dict[str, Any]:
    thr_pos = thr_bins[thr_bins > 0]
    log_thr = np.log(thr_pos) if len(thr_pos) else np.array([], dtype=float)
    log_mu = float(np.mean(log_thr)) if len(log_thr) else float("nan")
    log_sigma = float(np.std(log_thr, ddof=0)) if len(log_thr) else float("nan")
    jb_log, p_log = _jarque_bera(log_thr) if len(log_thr) else (float("nan"), float("nan"))
    return {
        "log_thr": log_thr,
        "log_mu": log_mu,
        "log_sigma": log_sigma,
        "jb_log": jb_log,
        "p_log": p_log,
    }


def print_summary(
    config: dict[str, Any],
    summary: dict[str, Any],
    arrival: dict[str, Any],
    non_overlapping: dict[str, Any],
    sliding: dict[str, Any],
    log_domain: dict[str, Any],
) -> None:

    print("\n=== Summary ===")
    print("\n--- Configuration ---")
    print(f"KEY_SIZE: {config['KEY_SIZE']} bits")
    print(f"NODE_BUFF_KEYS: {config['NODE_BUFF_KEYS']}")
    print(f"LINK_BUFF_BITS: {config['LINK_BUFF_BITS']} bits")
    print(f"LINKS_EMPTY_AT_START: {config['LINKS_EMPTY_AT_START']}")
    print(f"QKD_SKR: {config['QKD_SKR']} bits/s")
    print(f"LATENCY: {config['LATENCY']} s")
    print(f"TICK_INTERVAL: {config['TICK_INTERVAL']} s")
    print(f"WINDOW_SIZE: {config['WINDOW_SIZE']} s")
    print(f"SIM_DURATION: {config['SIM_DURATION']} s")
    print(f"HIST_BIN_WIDTH: {config['HIST_BIN_WIDTH']} bits/s")
    print(f"MIN_KEYS_IN_WINDOW: {config['MIN_KEYS_IN_WINDOW']}")
    print(f"BURN_IN: {config['BURN_IN']} s")
    print(f"S: {config['S']} | T: {config['T']}")
    print(f"Nodes: {config['nodes_count']} | Edges: {config['edges_count']}")
    print(
        f"Delivered keys: {summary['total_keys']} | Delivered bits: {summary['total_bits']} | "
        f"Sim duration: {config['SIM_DURATION']}s | Burn-in: {config['BURN_IN']}s"
    )

    if not summary["has_enough_arrivals"]:
        print("Not enough arrivals for meaningful statistics.")
        return

    print("\n--- Arrival process ---")
    print(
        f"Avg delivery rate: {arrival['rate_keys']:.6f} keys/s | {arrival['rate_bits']:.6f} bits/s"
    )
    print(
        f"Mean inter-arrival: {arrival['mean_iat']:.6f}s | CV(inter-arrival): {arrival['cv_iat']:.3f} "
        f"(Poisson would be ~1.0)"
    )

    print("\n--- Non-overlapping window throughput (preferred for distribution) ---")
    print(
        f"Samples: {len(non_overlapping['thr_bins'])} windows of {non_overlapping['bin_w']}s "
        f"(post burn-in)"
    )
    print(
        f"Quantization step: {non_overlapping['thr_step']:.6f} bits/s | "
        f"Unique throughput values: {len(non_overlapping['unique_thr'])}"
    )
    print(
        f"Zero-count windows: {non_overlapping['zero_windows']}/{len(non_overlapping['thr_bins'])} = "
        f"{non_overlapping['frac_zero']:.3f} (log() drops these)"
    )
    print(
        f"Mean:   {non_overlapping['mean_thr']:.6f} | Std: {non_overlapping['std_thr']:.6f}  "
        f"(std shown for reference)"
    )
    print(
        f"Median: {non_overlapping['median_thr']:.6f} | IQR: {non_overlapping['iqr']:.6f} | "
        f"MAD: {non_overlapping['mad']:.6f}"
    )
    print(f"P05:    {non_overlapping['p05']:.6f} | P95: {non_overlapping['p95']:.6f}")
    print(
        f"Skew:   {non_overlapping['skew_thr']:.3f} | Excess kurtosis: "
        f"{non_overlapping['kurt_thr']:.3f}"
    )
    print(
        f"Fano factor on window counts Var/Mean: {non_overlapping['fano']:.3f}  "
        f"(Poisson-ish ~1, bursty >1)"
    )
    print(
        f"JB normality (linear thr): JB={non_overlapping['jb_lin']:.3f}, "
        f"p≈{non_overlapping['p_lin']:.3g} (small p => not normal)"
    )
    print(
        f"JB normality (log thr>0): JB={log_domain['jb_log']:.3f}, "
        f"p≈{log_domain['p_log']:.3g} (small p => not log-normal)"
    )

    print("\n--- Sliding-window throughput series (correlated diagnostics) ---")
    if len(sliding["values"]):
        print(f"Recorded points: {len(sliding['values'])} (post burn-in)")
        print(f"Lag-1 autocorr: {sliding['lag1']:.3f}  (expect high due to overlap)")
        print(f"Crude ESS (AR(1) approx): {sliding['ess']:.1f}")
    else:
        print("No sliding-window points recorded (check MIN_KEYS_IN_WINDOW / burn-in).")

