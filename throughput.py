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
from collections import defaultdict
from random import choice
import analysis

random.seed(2026)

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



def simulate_single_pair(
    adj_list: defaultdict[str, list[str]],
    S: str,
    T: str,
    nodes: dict[str, Node],
    edges: dict[tuple[str, str], Link],
    sim_duration: float,
) -> list[float]:
    def get_edge(src: str, tgt: str) -> Link:
        return edges[(min(src, tgt), max(src, tgt))]

    events = []

    for _ in range(NODE_BUFF_KEYS):
        neighbour = choice(adj_list[S])
        waiting_time = get_edge(S, neighbour).reserve(0.0, KEY_SIZE)
        nodes[S].buffer_space -= 1
        push(events, (0.0 + waiting_time, ("link_ready", S, neighbour)))

    # Arrival timestamps at destination
    all_arrival_times = []

    while events:
        time, e = pop(events)
        if time > sim_duration:
            break

        et = e[0] # event type

        if et == "rcv_ready": # key material is reserved on link
            src, me = e[1], e[2]
            if nodes[me].buffer_space > 0: # buffer has space for key
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

    return all_arrival_times


def main(
    adj_list: defaultdict[str, list[str]],
    S: str,
    T: str,
    nodes: dict[str, Node],
    edges: dict[tuple[str, str], Link],
    config: dict[str, object],
):
    arrival_times = simulate_single_pair(
        adj_list, S, T, nodes, edges, config["SIM_DURATION"]
    )
    print(f"# of arrivals: {len(arrival_times)}")
    print("Simulation complete")

    analyzer = analysis.Analyzer(config)
    summary = analyzer.compute_summary(arrival_times)
    arrival = analyzer.compute_arrival_metrics(arrival_times, summary)
    non_overlapping = analyzer.compute_non_overlapping_throughput(arrival_times)
    sliding = analyzer.compute_sliding_window_metrics(arrival_times)
    log_domain = analyzer.compute_log_domain_metrics(non_overlapping.thr_bins)

    analyzer.print_summary(summary, arrival, non_overlapping, sliding, log_domain)
    analysis.plot_all(
        summary,
        sliding,
        non_overlapping,
        config,
        output_path=None,
        show=True,
    )


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

    S, T = "BOU", "PIT"
    print(f"S: {S}, T: {T}")

    config = {
        "KEY_SIZE": KEY_SIZE,
        "NODE_BUFF_KEYS": NODE_BUFF_KEYS,
        "LINK_BUFF_BITS": LINK_BUFF_BITS,
        "LINKS_EMPTY_AT_START": LINKS_EMPTY_AT_START,
        "QKD_SKR": QKD_SKR,
        "LATENCY": LATENCY,
        "TICK_INTERVAL": TICK_INTERVAL,
        "WINDOW_SIZE": WINDOW_SIZE,
        "SIM_DURATION": SIM_DURATION,
        "HIST_BIN_WIDTH": HIST_BIN_WIDTH,
        "MIN_KEYS_IN_WINDOW": MIN_KEYS_IN_WINDOW,
        "BURN_IN": BURN_IN,
        "S": S,
        "T": T,
        "nodes_count": len(nodes),
        "edges_count": len(edges),
    }
    main(adj_list, S, T, nodes, edges, config)
