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

from dataclasses import dataclass, asdict
import argparse
import json
import random
import os
from heapq import heappush as push, heappop as pop
import csv
from collections import defaultdict
from random import choice
from typing import Literal
import analysis
import signal

signal.signal(signal.SIGINT, signal.SIG_DFL)

random.seed(2026)

# Runtime settings (set by --quick flag)
QUICK_MODE = False
OUTPUT_BASE = "out"
DPI = 150
HEATMAP_SIM_DURATION = 100.0
HOP_SIM_DURATION = 100.0

# RANDOM WALK SIMULATION PARAMETERS
KEY_SIZE = 256  # bits per delivered key
NODE_BUFF_KEYS = 100000  # buffer capacity in *keys* (not bits)
LINK_BUFF_BITS = 100000  # reservable key material on a link (bits)
LINKS_EMPTY_AT_START = True
QKD_SKR = 1000  # secure key generation rate on each link (bits/s)
LATENCY = 0.05  # seconds 
SIM_DURATION = 1000.0  # seconds

# VISUALIZATION AND ANALYSIS PARAMETERS
TICK_INTERVAL = 10  # seconds between throughput measurements (sliding window)
WINDOW_SIZE = 5.0  # seconds for sliding window throughput
HIST_BIN_WIDTH = 100.0  # bits/s bins for histogram (non-overlapping samples)
MIN_KEYS_IN_WINDOW = 1  # min keys in window before recording sliding throughput
BURN_IN = 0 * WINDOW_SIZE  # ignore early transient in stats

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

@dataclass
class Packet:
    history: list[str] # includes source and destination nodes
    started_at: float
    finished_at: float | None

    def __lt__(self, other: 'Packet') -> bool:
        return self.started_at < other.started_at

def choose_next(p: Packet, neighbours: list[str], variant: Literal["random", "nonbacktracking", "lrv"]) -> str:
    if len(neighbours) == 1: return neighbours[0]
    assert len(neighbours) > 1
    if variant == "random": return choice(neighbours)
    elif variant == "nonbacktracking":
        if len(p.history) < 2:
            return choice(neighbours)
        prev_node = p.history[-2]
        other_nodes = [n for n in neighbours if n != prev_node]
        if not other_nodes:
            return prev_node
        return choice(other_nodes)
    elif variant == "lrv":
        assert len(p.history) > 0 # it should always contain the source node
        last_idx = {node: i for i, node in enumerate(p.history)}
        unvisited = [n for n in neighbours if n not in last_idx]
        if unvisited:
            return choice(unvisited)
        min_idx = min(last_idx[n] for n in neighbours)
        lrv = [n for n in neighbours if last_idx[n] == min_idx]
        return choice(lrv)
    else:
        raise ValueError(f"Invalid variant: {variant}")

class RelayNetwork:  # bidirected graph
    def __init__(
        self,
        node_list_csv: str,
        edge_list_csv: str,
        skr: float = QKD_SKR,
        latency: float = LATENCY,
    ):
        self.nodes: dict[str, Node] = {}
        self.adj_list: dict[str, list[str]] = defaultdict(list)
        self.edges: dict[tuple[str, str], Link] = {}
        self._node_ids: list[str] = []
        self._edge_pairs: list[tuple[str, str]] = []

        with open(node_list_csv, "r") as file:
            reader = csv.DictReader(file)
            for row in reader:
                node_id = row.get("Id") or row.get("ID") or row.get("id")
                if not node_id:
                    raise ValueError("Node CSV missing Id column")
                self.nodes[node_id] = Node(node_id)
                self._node_ids.append(node_id)

        with open(edge_list_csv, "r") as file:
            reader = csv.DictReader(file)
            for row in reader:
                src, tgt = row["Source"], row["Target"]
                if src not in self.nodes:
                    self.nodes[src] = Node(src)
                    self._node_ids.append(src)
                if tgt not in self.nodes:
                    self.nodes[tgt] = Node(tgt)
                    self._node_ids.append(tgt)
                self.adj_list[src].append(tgt)
                self.adj_list[tgt].append(src)
                key = (min(src, tgt), max(src, tgt))
                if key not in self.edges:
                    self.edges[key] = Link(src, tgt, skr, latency)
                    self._edge_pairs.append((src, tgt))

    def get_node(self, id: str) -> Node:
        return self.nodes[id]

    def get_edge(self, src: str, tgt: str) -> Link:
        return self.edges[(min(src, tgt), max(src, tgt))]

    def get_neighbours(self, id: str) -> list[str]:
        return self.adj_list[id]

    def node_ids(self) -> list[str]:
        return list(self._node_ids)

    def reset(self) -> None:
        self.nodes = {node_id: Node(node_id) for node_id in self._node_ids}
        self.adj_list = defaultdict(list)
        self.edges = {}
        for src, tgt in self._edge_pairs:
            self.adj_list[src].append(tgt)
            self.adj_list[tgt].append(src)
            key = (min(src, tgt), max(src, tgt))
            if key not in self.edges:
                self.edges[key] = Link(src, tgt, QKD_SKR, LATENCY)


def simulate_single_pair(
    graph: RelayNetwork,
    S: str,
    T: str,
    sim_duration: float | None = None,
    variant: Literal["random", "nonbacktracking", "lrv"] = "random",
    max_packets: int | None = None,
) -> list[Packet]:
    """
    Simulate packet transmission from S to T.
    Stop when sim_duration is exceeded OR max_packets are gathered (whichever comes first).
    At least one of sim_duration or max_packets must be provided.
    """
    if sim_duration is None and max_packets is None:
        raise ValueError("At least one of sim_duration or max_packets must be provided")
    
    events = []
    nodes = graph.nodes

    for _ in range(NODE_BUFF_KEYS):
        new_packet = Packet(history=[S], started_at=0.0, finished_at=None)
        chosen_neighbour = choose_next(new_packet, graph.get_neighbours(S), variant)
        waiting_time = graph.get_edge(S, chosen_neighbour).reserve(0.0, KEY_SIZE)
        nodes[S].buffer_space -= 1
        push(
            events,
            (0.0 + waiting_time, ("link_ready", S, chosen_neighbour, new_packet)),
        )

    # packets with arrival times and history
    arrived_packets: list[Packet] = []

    while events: # non-decreasing time event loop
        time, e = pop(events)
        if sim_duration is not None and time > sim_duration:
            break
        if max_packets is not None and len(arrived_packets) >= max_packets:
            break

        et = e[0] # event type
        p:Packet = e[3] # packet

        if et == "link_ready": # self-notification that material is retrieved
            me, neighbour = e[1], e[2]
            push(events, (time + LATENCY, ("rcv_ready", me, neighbour, p)))
        elif et == "rcv_ready": # sender received OTP key material from link
            # now we have to ensure that buffer has enough space
            # if not, append to waiting list of this node
            src, me = e[1], e[2]
            if nodes[me].buffer_space > 0: # buffer has space for key
                nodes[me].buffer_space -= 1
                push(events, (time + LATENCY, ("rcv_can_send", me, src, p)))
            else:
                nodes[me].waiting.append((src, p))

        elif et == "rcv_can_send":
            me, target = e[2], e[1]
            push(events, (time + LATENCY, ("rcv_key", me, target, p)))
            nodes[me].buffer_space += 1

            if nodes[me].waiting:
                next_waiting, next_packet = nodes[me].waiting.pop(0)
                nodes[me].buffer_space -= 1
                push(events, (time + LATENCY, ("rcv_can_send", me, next_waiting, next_packet)))
            elif me == S:
                new_packet = Packet(history=[S], started_at=time, finished_at=None)
                chosen_neighbour = choose_next(new_packet, graph.get_neighbours(S), variant)
                nodes[S].buffer_space -= 1
                waiting_time = graph.get_edge(S, chosen_neighbour).reserve(time, KEY_SIZE)
                push(
                    events,
                    (time + waiting_time, ("link_ready", S, chosen_neighbour, new_packet)),
                )

        elif et == "rcv_key":
            src: str = e[1]
            tgt: str = e[2]
            p.history.append(tgt)
            if tgt == T:
                p.finished_at = time
                arrived_packets.append(p)
                nodes[T].buffer_space += 1
                if nodes[T].waiting:
                    next_waiting = nodes[T].waiting.pop(0)
                    nodes[T].buffer_space -= 1
                    push(events, (time + LATENCY, ("rcv_can_send", T, next_waiting)))
            else:
                me = tgt
                chosen_neighbour = choose_next(p, graph.get_neighbours(me), variant)
                waiting_time = graph.get_edge(me, chosen_neighbour).reserve(time, KEY_SIZE)
                push(
                    events,
                    (time + waiting_time, ("link_ready", me, chosen_neighbour, p)),
                )

    return arrived_packets


def generate_paths_for_all_pairs(
    graph: RelayNetwork,
    variant: Literal["random", "nonbacktracking", "lrv"],
    output_dir: str,
    num_packets: int = 32,
) -> None:
    """
    Generate example paths for all pairs of nodes and save to JSONL files.
    Files are saved to output_dir/<variant>/paths/<src>-<tgt>.jsonl (lowercase, sorted order).
    """
    variant_prefix = {"random": "r", "nonbacktracking": "nb", "lrv": "lrv"}[variant]
    paths_dir = os.path.join(output_dir, variant_prefix, "paths")
    os.makedirs(paths_dir, exist_ok=True)
    
    node_ids = graph.node_ids()
    pairs_done = set()
    
    for src in node_ids:
        for tgt in node_ids:
            if src == tgt:
                continue
            # canonical pair order to avoid duplicates (src-tgt and tgt-src)
            pair_key = tuple(sorted([src, tgt]))
            if pair_key in pairs_done:
                continue
            pairs_done.add(pair_key)
            
            # reset graph state for each pair
            graph.reset()
            
            # simulate to get num_packets arrivals
            arrived = simulate_single_pair(
                graph, src, tgt, variant=variant, max_packets=num_packets
            )
            
            # write to jsonl file
            filename = f"{src.lower()}-{tgt.lower()}.jsonl"
            filepath = os.path.join(paths_dir, filename)
            
            with open(filepath, 'w') as f:
                for packet in arrived[:num_packets]:
                    record = {
                        "started_at": packet.started_at,
                        "finished_at": packet.finished_at,
                        "history": packet.history,
                    }
                    f.write(json.dumps(record) + "\n")
            
            print(f"  {src}-{tgt}: {len(arrived)} packets -> {filename}")


def main(
    graph: RelayNetwork,
    S: str,
    T: str,
    config: dict[str, object],
    output_dir: str = "out",
):
    variant = config["VARIANT_LONG"]
    arrived_packets = simulate_single_pair(
        graph, S, T, config["SIM_DURATION"], variant=variant
    )
    arrival_times = [p.finished_at for p in arrived_packets if p.finished_at is not None]
    print(f"# of arrivals: {len(arrival_times)}")
    print("Simulation complete")

    analyzer = analysis.Analyzer(config)
    summary = analyzer.compute_summary(arrival_times)
    arrival = analyzer.compute_arrival_metrics(arrival_times, summary)
    non_overlapping = analyzer.compute_non_overlapping_throughput(arrival_times)
    sliding = analyzer.compute_sliding_window_metrics(arrival_times)
    log_domain = analyzer.compute_log_domain_metrics(non_overlapping.thr_bins)

    # Create variant subdirectory
    variant_dir = os.path.join(output_dir, str(config['VARIANT']).lower())
    os.makedirs(variant_dir, exist_ok=True)
    
    analyzer.print_summary(
        summary,
        arrival,
        non_overlapping,
        sliding,
        log_domain,
        summary_path=os.path.join(variant_dir, "throughput_summary.txt"),
    )
    plot_all(
        summary,
        sliding,
        non_overlapping,
        config,
        output_path=os.path.join(variant_dir, "throughput.png"),
        output_dir=variant_dir,
        show=False,
    )


def plot_all(
    summary: analysis.Summary,
    sliding: analysis.SlidingWindowSeries,
    non_overlapping: analysis.NonOverlappingThroughput,
    config: dict[str, object],
    output_path: str | None = "throughput.png",
    output_dir: str = "out",
    show: bool = True,
):
    if not summary.has_enough_arrivals:
        return None, None

    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    analysis.plot_sliding_window(axes[0], sliding, config)
    analysis.plot_non_overlapping_histogram(axes[1], non_overlapping, config)

    plt.suptitle(
        f"{config['GRAPH']} | {config['VARIANT']} | "
        f"burn-in={config['BURN_IN']}s, sim={config['SIM_DURATION']}s",
        fontsize=12,
    )
    dpi = config.get("DPI", 150)
    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=dpi)
    if show:
        plt.show()
    if output_path:
        print(f"\nPlot saved to {output_path}")

    os.makedirs(output_dir, exist_ok=True)
    _save_single_plot(
        lambda ax: analysis.plot_sliding_window(ax, sliding, config),
        os.path.join(output_dir, "throughput_time_series.png"),
        dpi=dpi,
    )
    _save_single_plot(
        lambda ax: analysis.plot_non_overlapping_histogram(ax, non_overlapping, config),
        os.path.join(output_dir, "throughput_freq_distribution.png"),
        dpi=dpi,
    )
    return fig, axes


def _save_single_plot(plot_fn, path: str, dpi: int = 150) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 1, figsize=(6, 5))
    plot_fn(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)


def generate_pairwise_metrics(
    graph: RelayNetwork,
    selected_nodes: list[str],
    variant: Literal["random", "nonbacktracking", "lrv"],
    sim_duration: float,
    output_dir: str,
    graph_name: str,
    dpi: int = 150,
) -> None:
    """
    Generate heatmaps of throughput and hop counts between all pairs of selected nodes.
    Computes correlation between the two metrics.
    Saves CSV/TXT data and PNG visualizations to output_dir/<variant_prefix>/.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    
    # Create variant subdirectory
    variant_prefix = {"random": "r", "nonbacktracking": "nb", "lrv": "lrv"}[variant]
    variant_dir = os.path.join(output_dir, variant_prefix)
    os.makedirs(variant_dir, exist_ok=True)
    
    n = len(selected_nodes)
    throughput_matrix = np.zeros((n, n))
    hopcount_matrix = np.zeros((n, n))
    
    results = []
    total_pairs = n * (n - 1)
    pair_count = 0
    
    for i, src in enumerate(selected_nodes):
        for j, tgt in enumerate(selected_nodes):
            if src == tgt:
                throughput_matrix[i, j] = float('nan')
                hopcount_matrix[i, j] = float('nan')
                continue
            
            pair_count += 1
            print(f"  [{pair_count}/{total_pairs}] {src} -> {tgt}...", end=" ", flush=True)
            
            graph.reset()
            arrived = simulate_single_pair(
                graph, src, tgt, sim_duration=sim_duration, variant=variant
            )
            
            # throughput in kbit/s
            if arrived:
                last_arrival = max(p.finished_at for p in arrived if p.finished_at)
                keys_per_sec = len(arrived) / last_arrival if last_arrival > 0 else 0
                throughput_kbps = (keys_per_sec * KEY_SIZE) / 1000
                # hop count = len(history) - 1
                hop_counts = [len(p.history) - 1 for p in arrived]
                mean_hops = sum(hop_counts) / len(hop_counts)
            else:
                throughput_kbps = 0
                mean_hops = float('nan')
            
            throughput_matrix[i, j] = throughput_kbps
            hopcount_matrix[i, j] = mean_hops
            results.append({
                "source": src, "target": tgt, 
                "throughput_kbps": throughput_kbps, 
                "mean_hops": mean_hops,
                "packets": len(arrived)
            })
            print(f"{throughput_kbps:.2f} kbit/s, {mean_hops:.1f} hops ({len(arrived)} packets)")
    
    # Save CSV
    csv_path = os.path.join(variant_dir, f"{graph_name}_pairwise.csv")
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=["source", "target", "throughput_kbps", "mean_hops", "packets"])
        writer.writeheader()
        writer.writerows(results)
    print(f"\nCSV saved to {csv_path}")
    
    # Compute correlation between throughput and hop count
    valid_throughputs = []
    valid_hops = []
    for r in results:
        if not np.isnan(r["mean_hops"]) and r["throughput_kbps"] > 0:
            valid_throughputs.append(r["throughput_kbps"])
            valid_hops.append(r["mean_hops"])
    
    if len(valid_throughputs) > 2:
        # Pearson correlation
        mean_t = sum(valid_throughputs) / len(valid_throughputs)
        mean_h = sum(valid_hops) / len(valid_hops)
        
        cov = sum((t - mean_t) * (h - mean_h) for t, h in zip(valid_throughputs, valid_hops))
        std_t = (sum((t - mean_t)**2 for t in valid_throughputs)) ** 0.5
        std_h = (sum((h - mean_h)**2 for h in valid_hops)) ** 0.5
        
        pearson_r = cov / (std_t * std_h) if std_t > 0 and std_h > 0 else 0
    else:
        pearson_r = float('nan')
    
    # Save text summary
    txt_path = os.path.join(variant_dir, f"{graph_name}_pairwise.txt")
    with open(txt_path, 'w') as f:
        f.write(f"Pairwise Metrics: {graph_name.upper()}\n")
        f.write(f"Variant: {variant}\n")
        f.write(f"Simulation duration: {sim_duration}s\n")
        f.write(f"Selected nodes: {', '.join(selected_nodes)}\n")
        f.write(f"{'='*70}\n\n")
        f.write(f"Correlation (Pearson r) between throughput and hop count: {pearson_r:.4f}\n")
        f.write(f"  (negative = higher hops -> lower throughput, as expected)\n\n")
        f.write(f"{'Source':<8} {'Target':<8} {'Throughput':>12} {'Mean hops':>10} {'Packets':>8}\n")
        f.write(f"{'-'*70}\n")
        for r in results:
            f.write(f"{r['source']:<8} {r['target']:<8} {r['throughput_kbps']:>10.2f}  "
                   f"{r['mean_hops']:>10.2f} {r['packets']:>8}\n")
    print(f"Summary saved to {txt_path}")
    print(f"\n*** Correlation (Pearson r): {pearson_r:.4f} ***\n")
    
    # Create throughput heatmap
    _plot_heatmap(
        throughput_matrix, selected_nodes, 
        title=f"{graph_name.upper()} throughput heatmap ({variant})",
        cbar_label="Throughput (kbit/s)",
        output_path=os.path.join(variant_dir, f"{graph_name}_throughput_heatmap.png"),
        cmap="magma", fmt=".1f", dpi=dpi
    )
    
    # Create hop count heatmap
    _plot_heatmap(
        hopcount_matrix, selected_nodes,
        title=f"{graph_name.upper()} hop count heatmap ({variant})",
        cbar_label="Mean hop count",
        output_path=os.path.join(variant_dir, f"{graph_name}_hopcount_heatmap.png"),
        cmap="viridis", fmt=".1f", dpi=dpi
    )


def _plot_heatmap(
    matrix, labels: list[str], title: str, cbar_label: str, 
    output_path: str, cmap: str = "magma", fmt: str = ".1f", dpi: int = 150
) -> None:
    """Helper to plot a heatmap."""
    import matplotlib.pyplot as plt
    import numpy as np
    
    n = len(labels)
    fig, ax = plt.subplots(figsize=(10, 8))
    
    masked_data = np.ma.masked_invalid(matrix)
    
    colormap = plt.colormaps.get_cmap(cmap).copy()
    colormap.set_bad(color='#1a1a2e')
    
    im = ax.imshow(masked_data, cmap=colormap, aspect='equal')
    
    cbar = ax.figure.colorbar(im, ax=ax, shrink=0.8)
    cbar.ax.set_ylabel(cbar_label, rotation=-90, va="bottom", fontsize=11)
    
    ax.set_xticks(np.arange(n))
    ax.set_yticks(np.arange(n))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_yticklabels(labels, fontsize=9)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
    
    ax.set_xlabel("Destination", fontsize=12)
    ax.set_ylabel("Source", fontsize=12)
    ax.set_title(title, fontsize=14, pad=10)
    
    for i in range(n):
        for j in range(n):
            if i != j and not np.isnan(matrix[i, j]):
                val = matrix[i, j]
                text_color = "white" if val < masked_data.max() * 0.6 else "black"
                ax.text(j, i, f"{val:{fmt}}", ha="center", va="center", 
                       color=text_color, fontsize=7)
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=dpi, facecolor='white', edgecolor='none')
    plt.close(fig)
    print(f"Heatmap saved to {output_path}")


# Pre-selected nodes for heatmap (10 nodes each, geographically spread)
HEATMAP_NODES = {
    "geant": ["AMS", "ATH", "BER", "COP", "FRA", "LON", "MAD", "MIL", "PAR", "VIE"],
    "nsfnet": ["SEA", "PAO", "SAN", "HOU", "ATL", "PIT", "CMI", "BOU", "SLC", "ARB"],
}

# Fixed source nodes for hop count analysis
HOP_ANALYSIS_SOURCES = {
    "geant": "MIL",
    "nsfnet": "BOU",
    "secoqc": "BRE",
}


def analyze_hop_counts(
    graph: RelayNetwork,
    source: str,
    variant: Literal["random", "nonbacktracking", "lrv"],
    sim_duration: float,
    output_dir: str,
    graph_name: str,
    dpi: int = 150,
) -> None:
    """
    Analyze expected hop counts from a fixed source to all destinations.
    Saves text log and bar chart visualization.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    
    os.makedirs(output_dir, exist_ok=True)
    
    destinations = [n for n in graph.node_ids() if n != source]
    results = []
    
    total = len(destinations)
    for i, dest in enumerate(destinations):
        print(f"  [{i+1}/{total}] {source} -> {dest}...", end=" ", flush=True)
        
        graph.reset()
        arrived = simulate_single_pair(
            graph, source, dest, sim_duration=sim_duration, variant=variant
        )
        
        if arrived:
            # hop count = len(history) - 1 (history includes source and destination)
            hop_counts = [len(p.history) - 1 for p in arrived]
            mean_hops = sum(hop_counts) / len(hop_counts)
            min_hops = min(hop_counts)
            max_hops = max(hop_counts)
            std_hops = (sum((h - mean_hops)**2 for h in hop_counts) / len(hop_counts)) ** 0.5
        else:
            mean_hops = float('nan')
            min_hops = 0
            max_hops = 0
            std_hops = 0
        
        results.append({
            "destination": dest,
            "mean_hops": mean_hops,
            "min_hops": min_hops,
            "max_hops": max_hops,
            "std_hops": std_hops,
            "packets": len(arrived),
        })
        print(f"{mean_hops:.1f} hops (min={min_hops}, max={max_hops}, n={len(arrived)})")
    
    # Sort by mean hops ascending
    results.sort(key=lambda x: x["mean_hops"] if not np.isnan(x["mean_hops"]) else float('inf'))
    
    # Save text log
    variant_prefix = {"random": "r", "nonbacktracking": "nb", "lrv": "lrv"}[variant]
    variant_dir = os.path.join(output_dir, variant_prefix)
    os.makedirs(variant_dir, exist_ok=True)
    txt_path = os.path.join(variant_dir, "hop_counts.txt")
    with open(txt_path, 'w') as f:
        f.write(f"Hop Count Analysis: {graph_name.upper()}\n")
        f.write(f"Source: {source}\n")
        f.write(f"Variant: {variant}\n")
        f.write(f"Simulation duration: {sim_duration}s\n")
        f.write(f"{'='*60}\n\n")
        f.write(f"{'Destination':<12} {'Mean':>8} {'Std':>8} {'Min':>6} {'Max':>6} {'Packets':>8}\n")
        f.write(f"{'-'*60}\n")
        for r in results:
            f.write(f"{r['destination']:<12} {r['mean_hops']:>8.2f} {r['std_hops']:>8.2f} "
                   f"{r['min_hops']:>6} {r['max_hops']:>6} {r['packets']:>8}\n")
    print(f"\nLog saved to {txt_path}")
    
    # Create bar chart (same aspect ratio as time series: 6x5)
    fig, ax = plt.subplots(figsize=(6, 5))
    
    dests = [r["destination"] for r in results]
    means = [r["mean_hops"] for r in results]
    stds = [r["std_hops"] for r in results]
    
    # Color gradient based on hop count
    colors = plt.cm.viridis(np.linspace(0, 1, len(dests)))
    
    bars = ax.bar(range(len(dests)), means, yerr=stds, capsize=2, 
                  color=colors, edgecolor='white', linewidth=0.5,
                  error_kw={'ecolor': 'gray', 'alpha': 0.6, 'capthick': 1})
    
    ax.set_xticks(range(len(dests)))
    ax.set_xticklabels(dests, rotation=90, ha='center', fontsize=6)
    ax.set_xlabel("Destination", fontsize=10)
    ax.set_ylabel("Expected hop count", fontsize=10)
    ax.set_title(f"{graph_name.upper()} hop counts from {source} ({variant}, ±1σ)", fontsize=11)
    
    # Horizontal grid lines
    ax.grid(True, axis='y', alpha=0.3)
    ax.set_axisbelow(True)
    
    ax.set_ylim(bottom=0)
    plt.tight_layout()
    
    png_path = os.path.join(variant_dir, "hop_counts.png")
    plt.savefig(png_path, dpi=dpi, facecolor='white', edgecolor='none')
    plt.close(fig)
    print(f"Chart saved to {png_path}")


def analyze_edge_node_visits(
    graph: RelayNetwork,
    source: str,
    target: str,
    variant: Literal["random", "nonbacktracking", "lrv"],
    sim_duration: float,
    output_dir: str,
    graph_name: str,
    dpi: int = 150,
) -> None:
    """
    Analyze edge multiplicity and node hitting probability for a specific (source, target) pair.
    - Edge multiplicity: expected number of times each edge is traversed
    - Node hitting: probability of visiting each intermediate node at least once (excludes source/target)
    """
    import matplotlib.pyplot as plt
    import numpy as np
    from collections import Counter
    
    variant_prefix = {"random": "r", "nonbacktracking": "nb", "lrv": "lrv"}[variant]
    variant_dir = os.path.join(output_dir, variant_prefix)
    os.makedirs(variant_dir, exist_ok=True)
    
    print(f"  {source} -> {target}...", end=" ", flush=True)
    
    graph.reset()
    arrived = simulate_single_pair(
        graph, source, target, sim_duration=sim_duration, variant=variant
    )
    
    total_packets = len(arrived)
    edge_visit_counts = Counter()  # edge -> total visits across all packets
    node_hit_counts = Counter()    # node -> number of packets that visited it
    
    for p in arrived:
        visited_nodes = set()
        # Count edge traversals
        for k in range(len(p.history) - 1):
            edge = tuple(sorted([p.history[k], p.history[k+1]]))
            edge_visit_counts[edge] += 1
        # Count node visits (at least once per packet), excluding source and target
        for node in p.history:
            if node != source and node != target:
                visited_nodes.add(node)
        for node in visited_nodes:
            node_hit_counts[node] += 1
    
    print(f"{total_packets} packets")
    
    if total_packets == 0:
        print("No packets arrived, skipping analysis")
        return
    
    # Compute expected edge multiplicity (avg visits per packet)
    edge_multiplicity = {e: c / total_packets for e, c in edge_visit_counts.items()}
    # Compute node hitting probability (excluding source and target)
    node_hitting_prob = {n: c / total_packets for n, c in node_hit_counts.items()}
    
    # Save text summary
    txt_path = os.path.join(variant_dir, "edge_node_visits.txt")
    with open(txt_path, 'w') as f:
        f.write(f"Edge & Node Visit Analysis: {graph_name.upper()}\n")
        f.write(f"Source: {source}, Target: {target}\n")
        f.write(f"Variant: {variant}\n")
        f.write(f"Total packets: {total_packets}\n")
        f.write(f"{'='*60}\n\n")
        
        f.write("Edge Multiplicity (expected visits per packet, ascending):\n")
        f.write(f"{'-'*40}\n")
        for edge, mult in sorted(edge_multiplicity.items(), key=lambda x: x[1]):
            f.write(f"  {edge[0]}-{edge[1]}: {mult:.4f}\n")
        
        f.write(f"\nNode Hitting Probability (excludes {source}, {target}, ascending):\n")
        f.write(f"{'-'*40}\n")
        for node, prob in sorted(node_hitting_prob.items(), key=lambda x: x[1]):
            f.write(f"  {node}: {prob:.4f}\n")
    print(f"Summary saved to {txt_path}")
    
    # Plot edge multiplicity histogram (sorted ascending, with color gradient)
    fig, ax = plt.subplots(figsize=(6, 5))
    edges_sorted = sorted(edge_multiplicity.keys(), key=lambda e: edge_multiplicity[e])
    multiplicities = [edge_multiplicity[e] for e in edges_sorted]
    colors = plt.cm.plasma(np.linspace(0, 1, len(edges_sorted)))
    ax.bar(range(len(multiplicities)), multiplicities, color=colors, edgecolor='white', linewidth=0.5)
    ax.set_xlabel("Edge (sorted ascending)", fontsize=10)
    ax.set_ylabel("Expected visits per packet", fontsize=10)
    ax.set_title(f"{graph_name.upper()} edge multiplicity {source}→{target} ({variant})", fontsize=11)
    ax.grid(True, axis='y', alpha=0.3)
    ax.set_axisbelow(True)
    plt.tight_layout()
    png_path = os.path.join(variant_dir, "edge_multiplicity.png")
    plt.savefig(png_path, dpi=dpi, facecolor='white', edgecolor='none')
    plt.close(fig)
    print(f"Edge multiplicity chart saved to {png_path}")
    
    # Plot node hitting probability histogram (sorted ascending)
    fig, ax = plt.subplots(figsize=(6, 5))
    nodes_sorted = sorted(node_hitting_prob.keys(), key=lambda n: node_hitting_prob[n])
    probs = [node_hitting_prob[n] for n in nodes_sorted]
    colors = plt.cm.viridis(np.linspace(0, 1, len(nodes_sorted)))
    ax.bar(range(len(nodes_sorted)), probs, color=colors, edgecolor='white', linewidth=0.5)
    ax.set_xticks(range(len(nodes_sorted)))
    ax.set_xticklabels(nodes_sorted, rotation=90, ha='center', fontsize=6)
    ax.set_xlabel("Node (sorted ascending)", fontsize=10)
    ax.set_ylabel("Hitting probability", fontsize=10)
    ax.set_title(f"{graph_name.upper()} node hitting {source}→{target} ({variant})", fontsize=11)
    ax.grid(True, axis='y', alpha=0.3)
    ax.set_axisbelow(True)
    ax.set_ylim(0, 1.05)
    plt.tight_layout()
    png_path = os.path.join(variant_dir, "node_hitting.png")
    plt.savefig(png_path, dpi=dpi, facecolor='white', edgecolor='none')
    plt.close(fig)
    print(f"Node hitting chart saved to {png_path}")


def generate_hitting_heatmap(
    graph: RelayNetwork,
    selected_nodes: list[str],
    variant: Literal["random", "nonbacktracking", "lrv"],
    sim_duration: float,
    output_dir: str,
    graph_name: str,
    dpi: int = 150,
) -> None:
    """
    For each pair (s, t), find the intermediate node v with highest hitting probability.
    Display as a heatmap showing which node is most likely to be visited.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    from collections import Counter
    
    variant_prefix = {"random": "r", "nonbacktracking": "nb", "lrv": "lrv"}[variant]
    variant_dir = os.path.join(output_dir, variant_prefix)
    os.makedirs(variant_dir, exist_ok=True)
    
    n = len(selected_nodes)
    # Store the highest-hitting node for each pair
    max_hitting_node = [['' for _ in range(n)] for _ in range(n)]
    max_hitting_prob = np.zeros((n, n))
    
    results = []
    total_pairs = n * (n - 1)
    pair_count = 0
    
    for i, src in enumerate(selected_nodes):
        for j, tgt in enumerate(selected_nodes):
            if src == tgt:
                max_hitting_prob[i, j] = float('nan')
                continue
            
            pair_count += 1
            print(f"  [{pair_count}/{total_pairs}] {src} -> {tgt}...", end=" ", flush=True)
            
            graph.reset()
            arrived = simulate_single_pair(
                graph, src, tgt, sim_duration=sim_duration, variant=variant
            )
            
            if not arrived:
                max_hitting_prob[i, j] = float('nan')
                print("no packets")
                continue
            
            # Count node hits (excluding source and target)
            node_hit_counts = Counter()
            for p in arrived:
                visited = set(p.history)
                for node in visited:
                    if node != src and node != tgt:
                        node_hit_counts[node] += 1
            
            # Find node with highest hitting prob
            if node_hit_counts:
                best_node = max(node_hit_counts.keys(), key=lambda n: node_hit_counts[n])
                best_prob = node_hit_counts[best_node] / len(arrived)
            else:
                best_node = "-"
                best_prob = 0
            
            max_hitting_node[i][j] = best_node
            max_hitting_prob[i, j] = best_prob
            results.append({
                "source": src, "target": tgt, 
                "max_hitting_node": best_node, 
                "max_hitting_prob": best_prob,
                "packets": len(arrived)
            })
            print(f"{best_node} ({best_prob:.2f})")
    
    # Save text summary
    txt_path = os.path.join(variant_dir, f"{graph_name}_hitting_heatmap.txt")
    with open(txt_path, 'w') as f:
        f.write(f"Max Hitting Node Heatmap: {graph_name.upper()}\n")
        f.write(f"Variant: {variant}\n")
        f.write(f"{'='*60}\n\n")
        f.write(f"{'Source':<8} {'Target':<8} {'MaxHitNode':<12} {'Prob':>8} {'Packets':>8}\n")
        f.write(f"{'-'*60}\n")
        for r in results:
            f.write(f"{r['source']:<8} {r['target']:<8} {r['max_hitting_node']:<12} "
                   f"{r['max_hitting_prob']:>8.4f} {r['packets']:>8}\n")
    print(f"Summary saved to {txt_path}")
    
    # Create heatmap with node labels
    fig, ax = plt.subplots(figsize=(10, 8))
    
    masked_data = np.ma.masked_invalid(max_hitting_prob)
    cmap = plt.colormaps.get_cmap("YlOrRd").copy()
    cmap.set_bad(color='#1a1a2e')
    
    im = ax.imshow(masked_data, cmap=cmap, aspect='equal', vmin=0, vmax=1)
    
    cbar = ax.figure.colorbar(im, ax=ax, shrink=0.8)
    cbar.ax.set_ylabel("Hitting probability", rotation=-90, va="bottom", fontsize=11)
    
    ax.set_xticks(np.arange(n))
    ax.set_yticks(np.arange(n))
    ax.set_xticklabels(selected_nodes, fontsize=9)
    ax.set_yticklabels(selected_nodes, fontsize=9)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
    
    ax.set_xlabel("Destination", fontsize=12)
    ax.set_ylabel("Source", fontsize=12)
    ax.set_title(f"{graph_name.upper()} max hitting node ({variant})", fontsize=14, pad=10)
    
    # Add node labels in cells
    for i in range(n):
        for j in range(n):
            if i != j and max_hitting_node[i][j]:
                prob = max_hitting_prob[i, j]
                text_color = "white" if prob > 0.5 else "black"
                ax.text(j, i, f"{max_hitting_node[i][j]}\n{prob:.2f}", 
                       ha="center", va="center", color=text_color, fontsize=6)
    
    plt.tight_layout()
    png_path = os.path.join(variant_dir, f"{graph_name}_hitting_heatmap.png")
    plt.savefig(png_path, dpi=dpi, facecolor='white', edgecolor='none')
    plt.close(fig)
    print(f"Heatmap saved to {png_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Random walk key relaying throughput simulation")
    parser.add_argument("--quick", action="store_true", 
                       help="Quick mode: shorter simulations (10s), lower DPI (72), output to quick/")
    args = parser.parse_args()
    
    # Apply quick mode settings
    if args.quick:
        QUICK_MODE = True
        OUTPUT_BASE = "quick"
        DPI = 72
        HEATMAP_SIM_DURATION = 10.0
        HOP_SIM_DURATION = 10.0
        SIM_DURATION = 100.0  # main throughput sim
        print("*** QUICK MODE: shorter simulations, lower quality images ***\n")
    else:
        OUTPUT_BASE = "out"
        DPI = 150
        HEATMAP_SIM_DURATION = 100.0
        HOP_SIM_DURATION = 100.0
    
    graphs = [
        ("geant", "graphs/geant/geant_nodes.csv", "graphs/geant/geant_edges.csv"),
        ("nsfnet", "graphs/nsfnet/nsfnet_nodes.csv", "graphs/nsfnet/nsfnet_edges.csv"),
        ("secoqc", "graphs/secoqc/secoqc_nodes.csv", "graphs/secoqc/secoqc_edges.csv"),
    ]

    variants = ["random", "nonbacktracking", "lrv"]
    graph_pairs = {
        "geant": ("MIL", "COP"),
        "nsfnet": ("BOU", "PIT"),
        "secoqc": ("BRE", "SIE"),
    }

    for name, nodes_csv, edges_csv in graphs:
        graph = RelayNetwork(nodes_csv, edges_csv)
        if name not in graph_pairs:
            print(f"{name}: missing S/T pair")
            continue
        S, T = graph_pairs[name]
        if S not in graph.nodes or T not in graph.nodes:
            print(f"{name}: S/T not in node list ({S}, {T})")
            continue
        print(f"{name}: S={S}, T={T}")
        output_dir = os.path.join(OUTPUT_BASE, name)
        
        sim_duration = 100.0 if args.quick else SIM_DURATION
        
        for variant in variants:
            graph.reset()
            config = {
                "KEY_SIZE": KEY_SIZE,
                "NODE_BUFF_KEYS": NODE_BUFF_KEYS,
                "LINK_BUFF_BITS": LINK_BUFF_BITS,
                "LINKS_EMPTY_AT_START": LINKS_EMPTY_AT_START,
                "QKD_SKR": QKD_SKR,
                "LATENCY": LATENCY,
                "TICK_INTERVAL": TICK_INTERVAL,
                "WINDOW_SIZE": WINDOW_SIZE,
                "SIM_DURATION": sim_duration,
                "HIST_BIN_WIDTH": HIST_BIN_WIDTH,
                "MIN_KEYS_IN_WINDOW": MIN_KEYS_IN_WINDOW,
                "BURN_IN": BURN_IN,
                "S": S,
                "T": T,
                "VARIANT": {"random": "R", "nonbacktracking": "NB", "lrv": "LRV"}[
                    variant
                ],
                "VARIANT_LONG": variant,
                "GRAPH": name,
                "nodes_count": len(graph.nodes),
                "edges_count": len(graph.edges),
                "DPI": DPI,
            }
            main(graph, S, T, config, output_dir=output_dir)
        
        # Generate example paths for all pairs (all 3 variants)
        # for path_variant in ["random", "nonbacktracking", "lrv"]:
        #     print(f"\n{name}: generating {path_variant} paths for all pairs...")
        #     graph.reset()
        #     generate_paths_for_all_pairs(graph, path_variant, output_dir, num_packets=32)
        
        # Generate pairwise metrics heatmaps (for geant and nsfnet only)
        if name in HEATMAP_NODES:
            print(f"\n{name}: generating pairwise metrics (throughput & hop counts)...")
            graph.reset()
            generate_pairwise_metrics(
                graph,
                selected_nodes=HEATMAP_NODES[name],
                variant="nonbacktracking",
                sim_duration=HEATMAP_SIM_DURATION,
                output_dir=output_dir,
                graph_name=name,
                dpi=DPI,
            )
        
        # Analyze hop counts from fixed source (all 3 variants)
        if name in HOP_ANALYSIS_SOURCES:
            hop_source = HOP_ANALYSIS_SOURCES[name]
            for hop_variant in ["random", "nonbacktracking", "lrv"]:
                print(f"\n{name}: analyzing {hop_variant} hop counts from {hop_source}...")
                graph.reset()
                analyze_hop_counts(
                    graph,
                    source=hop_source,
                    variant=hop_variant,
                    sim_duration=HOP_SIM_DURATION,
                    output_dir=output_dir,
                    graph_name=name,
                    dpi=DPI,
                )
        
        # Analyze edge multiplicity and node hitting (all 3 variants)
        if name in graph_pairs:
            visit_source, visit_target = graph_pairs[name]
            for visit_variant in ["random", "nonbacktracking", "lrv"]:
                print(f"\n{name}: analyzing {visit_variant} edge/node visits {visit_source}→{visit_target}...")
                graph.reset()
                analyze_edge_node_visits(
                    graph,
                    source=visit_source,
                    target=visit_target,
                    variant=visit_variant,
                    sim_duration=HOP_SIM_DURATION,
                    output_dir=output_dir,
                    graph_name=name,
                    dpi=DPI,
                )
        
        # Generate hitting probability heatmap (for geant and nsfnet only)
        if name in HEATMAP_NODES:
            print(f"\n{name}: generating hitting probability heatmap...")
            graph.reset()
            generate_hitting_heatmap(
                graph,
                selected_nodes=HEATMAP_NODES[name],
                variant="nonbacktracking",
                sim_duration=HEATMAP_SIM_DURATION,
                output_dir=output_dir,
                graph_name=name,
                dpi=DPI,
            )
