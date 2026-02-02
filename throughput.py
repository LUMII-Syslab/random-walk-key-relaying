"""
Measures transmission throughput of random walk key relaying in a QKD network.

Notes / fixes:
- Throughput over a window is a scaled COUNT of arrivals in that window.
  If arrivals were Poisson, counts ~ Poisson, throughput is scaled Poisson (discrete, skewed if mean small).
- Sliding-window samples are strongly autocorrelated; histogram of those samples is not an i.i.d. distribution sample.
- We therefore compute both:
    (1) sliding-window throughput time series (for dynamics)
    (2) non-overlapping-window throughput samples (for distribution/statistics)
"""

import random
from heapq import heappush as push, heappop as pop
import sys
import csv
from collections import defaultdict, deque
from random import choice
import matplotlib.pyplot as plt
import numpy as np

import signal

signal.signal(signal.SIGINT, signal.SIG_DFL)

random.seed(42)

KEY_SIZE = 12  # bits per delivered key (toy)
NODE_BUFF_KEYS = 10000  # buffer capacity in *keys* (not bits)
LINK_BUFF_BITS = 10000  # reservable key material on a link (bits)
LINKS_EMPTY_AT_START = True
QKD_SKR = 6  # secure key generation rate on each link (bits/s)
LATENCY = 0  # seconds
TICK_INTERVAL = 10  # seconds between throughput measurements (sliding window)
WINDOW_SIZE = 20.0  # seconds for sliding window throughput
SIM_DURATION = 10000.0  # seconds
HIST_BIN_WIDTH = 0.05  # bits/s bins for histogram (non-overlapping samples)
MIN_KEYS_IN_WINDOW = 1  # min keys in window before recording sliding throughput
BURN_IN = 5 * WINDOW_SIZE  # ignore early transient in stats

import math

class Node:
    def __init__(self, name: str):
        self.name = name
        self.waiting = []  # FIFO list of senders waiting for buffer
        self.buffer_space = NODE_BUFF_KEYS  # capacity in keys


class Link:
    def __init__(self, src: str, tgt: str, skr: float, latency: float):
        self.src = src
        self.tgt = tgt
        self.skr = skr
        self.latency = latency
        self.bit_balance = 0.0
        if not LINKS_EMPTY_AT_START:
            self.bit_balance = float(LINK_BUFF_BITS)
        self.last_request = 0.0

    def reserve(self, current_time: float, necessary_bits: int) -> float:
        """
        Reserve necessary bits for OTP on this link.
        Returns waiting time until the reservation will be satisfied.
        """
        if current_time < self.last_request:
            raise ValueError(
                f"current_time {current_time} < last_request {self.last_request}"
            )
        if necessary_bits > LINK_BUFF_BITS:
            raise ValueError(
                f"necessary_bits {necessary_bits} > LINK_BUFF_BITS {LINK_BUFF_BITS}"
            )

        time_delta = current_time - self.last_request
        self.bit_balance += time_delta * self.skr

        waiting_time = max(0.0, (necessary_bits - self.bit_balance) / self.skr)

        # IMPORTANT: last_request is the time we *issued* the reservation, not when it's fulfilled.
        self.last_request = current_time
        self.bit_balance -= necessary_bits
        return waiting_time


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
    Jarque–Bera normality test statistic and (approx) p-value.
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

def main(
    adj_list: defaultdict[str, list[str]],
    S: str,
    T: str,
    nodes: dict[str, Node],
    edges: dict[tuple[str, str], Link],
):
    def get_edge(src: str, tgt: str) -> Link:
        return edges[(min(src, tgt), max(src, tgt))]

    events = []

    # Inject an initial flood to saturate (your original behavior).
    # This creates a transient; we drop BURN_IN in stats.
    for _ in range(NODE_BUFF_KEYS):
        neighbour = choice(adj_list[S])
        waiting_time = get_edge(S, neighbour).reserve(0.0, KEY_SIZE)
        nodes[S].buffer_space -= 1
        push(events, (0.0 + waiting_time, ("link_ready", S, neighbour)))

    # Arrival timestamps at destination
    arrival_timestamps = deque()  # for sliding window
    all_arrival_times = []  # for non-overlapping window binning

    # Sliding-window throughput measurements
    throughput_times = []
    throughput_values = []

    # Schedule first tick
    push(events, (TICK_INTERVAL, ("tick",)))

    while events:
        time, e = pop(events)
        if time > SIM_DURATION:
            break

        et = e[0]

        if et == "tick":
            cutoff = time - WINDOW_SIZE
            while arrival_timestamps and arrival_timestamps[0] < cutoff:
                arrival_timestamps.popleft()

            keys_in_window = len(arrival_timestamps)
            throughput = (keys_in_window * KEY_SIZE) / WINDOW_SIZE

            if time >= BURN_IN and keys_in_window >= MIN_KEYS_IN_WINDOW:
                throughput_times.append(time)
                throughput_values.append(throughput)

            # keep the print lightweight but informative
            if int(time) % 1000 == 0:  # every ~1000s
                print(
                    f"t={time:8.1f}s | sliding throughput={throughput:8.3f} bits/s | keys_in_window={keys_in_window}"
                )

            push(events, (time + TICK_INTERVAL, ("tick",)))

        elif et == "rcv_ready":
            src, me = e[1], e[2]
            if nodes[me].buffer_space > 0:
                nodes[me].buffer_space -= 1
                push(events, (time + LATENCY, ("rcv_can_send", me, src)))
            else:
                nodes[me].waiting.append(src)

        elif et == "rcv_can_send":
            me, target = e[2], e[1]
            push(events, (time + LATENCY, ("rcv_key", me, target)))
            nodes[me].buffer_space += 1

            if nodes[me].waiting:
                next_waiting = nodes[me].waiting.pop(0)
                nodes[me].buffer_space -= 1
                push(events, (time + LATENCY, ("rcv_can_send", me, next_waiting)))
            elif me == S:
                neighbour = choice(adj_list[S])
                nodes[S].buffer_space -= 1
                waiting_time = get_edge(S, neighbour).reserve(time, KEY_SIZE)
                push(events, (time + waiting_time, ("link_ready", S, neighbour)))

        elif et == "rcv_key":
            src, tgt = e[1], e[2]
            if tgt == T:
                arrival_timestamps.append(time)
                all_arrival_times.append(time)

                nodes[T].buffer_space += 1
                if nodes[T].waiting:
                    next_waiting = nodes[T].waiting.pop(0)
                    nodes[T].buffer_space -= 1
                    push(events, (time + LATENCY, ("rcv_can_send", T, next_waiting)))
            else:
                me = tgt
                neighbour = choice(adj_list[me])
                waiting_time = get_edge(me, neighbour).reserve(time, KEY_SIZE)
                push(events, (time + waiting_time, ("link_ready", me, neighbour)))

        elif et == "link_ready":
            me, neighbour = e[1], e[2]
            push(events, (time + LATENCY, ("rcv_ready", me, neighbour)))

    # -----------------------
    # Post-processing metrics
    # -----------------------
    print("\n=== Summary ===")
    print("\n--- Configuration ---")
    print(f"KEY_SIZE: {KEY_SIZE} bits")
    print(f"NODE_BUFF_KEYS: {NODE_BUFF_KEYS}")
    print(f"LINK_BUFF_BITS: {LINK_BUFF_BITS} bits")
    print(f"LINKS_EMPTY_AT_START: {LINKS_EMPTY_AT_START}")
    print(f"QKD_SKR: {QKD_SKR} bits/s")
    print(f"LATENCY: {LATENCY} s")
    print(f"TICK_INTERVAL: {TICK_INTERVAL} s")
    print(f"WINDOW_SIZE: {WINDOW_SIZE} s")
    print(f"SIM_DURATION: {SIM_DURATION} s")
    print(f"HIST_BIN_WIDTH: {HIST_BIN_WIDTH} bits/s")
    print(f"MIN_KEYS_IN_WINDOW: {MIN_KEYS_IN_WINDOW}")
    print(f"BURN_IN: {BURN_IN} s")
    print(f"S: {S} | T: {T}")
    print(f"Nodes: {len(nodes)} | Edges: {len(edges)}")
    total_keys = len(all_arrival_times)
    total_bits = total_keys * KEY_SIZE
    print(
        f"Delivered keys: {total_keys} | Delivered bits: {total_bits} | Sim duration: {SIM_DURATION}s | Burn-in: {BURN_IN}s"
    )

    if total_keys < 2:
        print("Not enough arrivals for meaningful statistics.")
        return

    all_arr = np.array(all_arrival_times, dtype=float)

    # Non-overlapping window binning (better for distribution checks)
    bin_w = WINDOW_SIZE
    edges_bins = np.arange(0.0, SIM_DURATION + bin_w, bin_w)
    counts, _ = np.histogram(all_arr, bins=edges_bins)
    bin_centers = edges_bins[:-1] + bin_w / 2.0
    mask = bin_centers >= BURN_IN
    counts_ss = counts[mask]
    thr_bins = counts_ss * KEY_SIZE / bin_w  # bits/s
    thr_step = KEY_SIZE / bin_w
    unique_thr = np.unique(thr_bins)
    zero_windows = int(np.sum(counts_ss == 0))
    frac_zero = zero_windows / len(counts_ss) if len(counts_ss) else float("nan")

    # Arrival process metrics
    inter = np.diff(all_arr)
    mean_iat = float(np.mean(inter))
    cv_iat = float(np.std(inter, ddof=0) / mean_iat) if mean_iat > 0 else float("nan")
    rate_keys = float(total_keys / SIM_DURATION)
    rate_bits = float(total_bits / SIM_DURATION)

    # Sliding-window series metrics (correlated!)
    if throughput_values:
        sw = np.array(throughput_values, dtype=float)
        sw_lag1 = _lag1_autocorr(sw)
        # crude AR(1) effective sample size estimate (diagnostic, not gospel)
        ess = (
            float(len(sw) * (1 - sw_lag1) / (1 + sw_lag1))
            if abs(sw_lag1) < 0.999
            else float("nan")
        )
    else:
        sw = np.array([], dtype=float)
        sw_lag1, ess = float("nan"), float("nan")

    # Robust stats on non-overlapping samples
    def q(a, p):
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

    # Poisson-ish diagnostic: Fano factor on counts in non-overlapping windows
    mean_c = float(np.mean(counts_ss)) if len(counts_ss) else float("nan")
    var_c = float(np.var(counts_ss, ddof=0)) if len(counts_ss) else float("nan")
    fano = (var_c / mean_c) if mean_c > 0 else float("nan")

    # Log-domain diagnostics (for "log-normal" eyeballing)
    thr_pos = thr_bins[thr_bins > 0]
    log_thr = np.log(thr_pos) if len(thr_pos) else np.array([], dtype=float)
    log_mu = float(np.mean(log_thr)) if len(log_thr) else float("nan")
    log_sigma = float(np.std(log_thr, ddof=0)) if len(log_thr) else float("nan")
    jb_log, p_log = _jarque_bera(log_thr) if len(log_thr) else (float("nan"), float("nan"))
    jb_lin, p_lin = _jarque_bera(thr_bins) if len(thr_bins) else (float("nan"), float("nan"))

    print("\n--- Arrival process ---")
    print(f"Avg delivery rate: {rate_keys:.6f} keys/s | {rate_bits:.6f} bits/s")
    print(
        f"Mean inter-arrival: {mean_iat:.6f}s | CV(inter-arrival): {cv_iat:.3f} (Poisson would be ~1.0)"
    )

    print("\n--- Non-overlapping window throughput (preferred for distribution) ---")
    print(f"Samples: {len(thr_bins)} windows of {bin_w}s (post burn-in)")
    print(f"Quantization step: {thr_step:.6f} bits/s | Unique throughput values: {len(unique_thr)}")
    print(f"Zero-count windows: {zero_windows}/{len(counts_ss)} = {frac_zero:.3f} (log() drops these)")
    print(f"Mean:   {mean_thr:.6f} | Std: {std_thr:.6f}  (std shown for reference)")
    print(f"Median: {median_thr:.6f} | IQR: {iqr:.6f} | MAD: {mad:.6f}")
    print(f"P05:    {p05:.6f} | P95: {p95:.6f}")
    print(f"Skew:   {skew_thr:.3f} | Excess kurtosis: {kurt_thr:.3f}")
    print(
        f"Fano factor on window counts Var/Mean: {fano:.3f}  (Poisson-ish ~1, bursty >1)"
    )
    print(f"JB normality (linear thr): JB={jb_lin:.3f}, p≈{p_lin:.3g} (small p => not normal)")
    print(f"JB normality (log thr>0): JB={jb_log:.3f}, p≈{p_log:.3g} (small p => not log-normal)")

    print("\n--- Sliding-window throughput series (correlated diagnostics) ---")
    if len(sw):
        print(f"Recorded points: {len(sw)} (post burn-in)")
        print(f"Lag-1 autocorr: {sw_lag1:.3f}  (expect high due to overlap)")
        print(f"Crude ESS (AR(1) approx): {ess:.1f}")
    else:
        print("No sliding-window points recorded (check MIN_KEYS_IN_WINDOW / burn-in).")

    # -------------
    # Plotting
    # -------------
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    ax1 = axes[0, 0]  # time series
    ax2 = axes[0, 1]  # linear histogram
    ax3 = axes[1, 0]  # log histogram
    ax4 = axes[1, 1]  # P–P plot for log domain

    mean_color = "tab:orange"
    median_color = "tab:green"

    # Left: time series (sliding window)
    if len(sw):
        ax1.plot(throughput_times, throughput_values, linewidth=0.8, alpha=0.7)
        ax1.axhline(
            y=float(np.mean(sw)),
            linestyle="--",
            linewidth=1.5,
            color=mean_color,
            label=f"Mean: {np.mean(sw):.3f}",
        )
        ax1.axhline(
            y=float(np.median(sw)),
            linestyle="-.",
            linewidth=1.5,
            color=median_color,
            label=f"Median: {np.median(sw):.3f}",
        )
        ax1.set_title(f"Sliding-window Throughput: {S} → {T}")
    else:
        ax1.set_title("Sliding-window Throughput (no samples)")
    ax1.set_xlabel("Time (s)")
    ax1.set_ylabel("Throughput (bits/s)")
    ax1.grid(True, alpha=0.3)
    ax1.legend(loc="upper right")

    # Top-right: histogram of NON-overlapping window throughput (quantized -> use step bins)
    if len(thr_bins):
        bin_min = np.floor(thr_bins.min() / thr_step) * thr_step
        bin_max = np.ceil(thr_bins.max() / thr_step) * thr_step
        bins = np.arange(bin_min - 0.5 * thr_step, bin_max + 1.5 * thr_step, thr_step)

        ax2.hist(thr_bins, bins=bins, edgecolor="black", alpha=0.7)
        ax2.axvline(
            x=mean_thr,
            linestyle="--",
            linewidth=1.5,
            color=mean_color,
            label=f"Mean: {mean_thr:.3f}",
        )
        ax2.axvline(
            x=median_thr,
            linestyle="-.",
            linewidth=1.5,
            color=median_color,
            label=f"Median: {median_thr:.3f}",
        )
        ax2.axvline(
            x=p05, linestyle=":", linewidth=1.2, label=f"P05/P95: {p05:.3f}/{p95:.3f}"
        )
        ax2.axvline(x=p95, linestyle=":", linewidth=1.2)
        ax2.set_title(f"Non-overlapping Window Throughput (bin={bin_w}s)")
        ax2.set_xlabel("Throughput (bits/s)")
        ax2.set_ylabel("Frequency")
        ax2.grid(True, alpha=0.3, axis="y")
        ax2.legend(loc="upper right")
    else:
        ax2.set_title("Histogram (no samples)")
        ax2.set_axis_off()

    # Bottom-left: histogram of log(throughput) for thr>0 with fitted normal overlay
    if len(log_thr):
        ax3.hist(log_thr, bins="auto", density=True, edgecolor="black", alpha=0.7)
        xs = np.linspace(log_thr.min(), log_thr.max(), 200)
        ax3.plot(xs, _norm_pdf(xs, log_mu, log_sigma), linewidth=1.5,
                 label=f"Normal fit μ={log_mu:.3f}, σ={log_sigma:.3f}")
        ax3.set_title("log(Throughput) density (thr>0)")
        ax3.set_xlabel("log(bits/s)")
        ax3.set_ylabel("Density")
        ax3.grid(True, alpha=0.3, axis="y")
        ax3.legend(loc="upper right")
    else:
        ax3.set_title("log(Throughput) (no positive samples)")
        ax3.set_axis_off()

    # Bottom-right: P–P plot of log(throughput) vs fitted normal
    if len(log_thr) >= 10 and log_sigma > 0:
        x_sorted = np.sort(log_thr)
        n = len(x_sorted)
        emp = (np.arange(1, n + 1) - 0.5) / n
        theo = _norm_cdf(x_sorted, log_mu, log_sigma)
        ax4.plot(theo, emp, ".", alpha=0.6)
        ax4.plot([0, 1], [0, 1], linestyle="--", linewidth=1.2)
        ax4.set_title("P–P plot: log(thr) vs fitted normal")
        ax4.set_xlabel("Theoretical CDF")
        ax4.set_ylabel("Empirical CDF")
        ax4.grid(True, alpha=0.3)
    else:
        ax4.set_title("P–P plot (insufficient log samples)")
        ax4.set_axis_off()

    plt.suptitle(f"Random Walk Key Relay (burn-in={BURN_IN}s, sim={SIM_DURATION}s)", fontsize=12)
    plt.tight_layout()
    plt.savefig("throughput.png", dpi=150)
    plt.show()
    print("\nPlot saved to throughput.png")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: throughput.py <edge_list_csv>")
        sys.exit(1)

    edge_list_csv = sys.argv[1]
    node_id_set = set()
    adj_list = defaultdict(list)

    with open(edge_list_csv, "r") as file:
        reader = csv.DictReader(file)
        for row in reader:
            src, tgt = row["Source"], row["Target"]
            node_id_set.add(src)
            node_id_set.add(tgt)
            adj_list[src].append(tgt)
            adj_list[tgt].append(src)

    nodes = {node_id: Node(node_id) for node_id in node_id_set}
    edges = {}
    for src in node_id_set:
        for tgt in adj_list[src]:
            if src < tgt:
                edges[(src, tgt)] = Link(src, tgt, QKD_SKR, LATENCY)

    sorted_nodes = sorted(node_id_set)
    if len(sorted_nodes) < 2:
        print("Need at least 2 nodes")
        sys.exit(1)

    S, T = sorted_nodes[0], sorted_nodes[-1]
    print(f"S: {S}, T: {T}")
    main(adj_list, S, T, nodes, edges)
