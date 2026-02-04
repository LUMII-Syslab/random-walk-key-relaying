"""
Pure Python simulation of random walk key relaying in a QKD network.

This module is designed to be PyPy-compatible (no numpy/matplotlib dependencies).
Run simulations with: pypy3 throughput.py --mode sim
"""

from dataclasses import dataclass, asdict, field
import json
import os
import csv
from heapq import heappush as push, heappop as pop
from collections import defaultdict
from random import choice
from typing import Literal
import random

# Default simulation parameters
DEFAULT_KEY_SIZE = 256  # bits per delivered key
DEFAULT_NODE_BUFF_KEYS = 100000  # buffer capacity in *keys* (not bits)
DEFAULT_LINK_BUFF_BITS = 100000  # reservable key material on a link (bits)
DEFAULT_LINKS_EMPTY_AT_START = True
DEFAULT_QKD_SKR = 1000  # secure key generation rate on each link (bits/s)
DEFAULT_LATENCY = 0.05  # seconds
DEFAULT_SIM_DURATION = 1000.0  # seconds


@dataclass
class SimConfig:
    """Configuration for a simulation run."""
    key_size: int = DEFAULT_KEY_SIZE
    node_buff_keys: int = DEFAULT_NODE_BUFF_KEYS
    link_buff_bits: int = DEFAULT_LINK_BUFF_BITS
    links_empty_at_start: bool = DEFAULT_LINKS_EMPTY_AT_START
    qkd_skr: float = DEFAULT_QKD_SKR
    latency: float = DEFAULT_LATENCY
    sim_duration: float = DEFAULT_SIM_DURATION
    random_seed: int = 2026

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "SimConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class Node:
    def __init__(self, name: str, buff_keys: int):
        self.name = name
        self.waiting = []  # FIFO list of senders waiting for buffer
        self.buffer_space = buff_keys  # capacity in keys


class Link:
    def __init__(self, src: str, tgt: str, skr: float, latency: float, 
                 link_buff_bits: int, links_empty_at_start: bool):
        self.src = src
        self.tgt = tgt
        self.skr = skr
        self.latency = latency
        self.link_buff_bits = link_buff_bits
        self.bit_balance = 0.0
        if not links_empty_at_start:
            self.bit_balance = float(link_buff_bits)
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
        if necessary_bits > self.link_buff_bits:
            raise ValueError(
                f"necessary_bits {necessary_bits} > link_buff_bits {self.link_buff_bits}"
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
    history: list  # includes source and destination nodes (list[str])
    started_at: float
    finished_at: float | None

    def __lt__(self, other: "Packet") -> bool:
        return self.started_at < other.started_at

    def to_dict(self) -> dict:
        return {
            "history": self.history,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Packet":
        return cls(
            history=d["history"],
            started_at=d["started_at"],
            finished_at=d.get("finished_at"),
        )


def choose_next(
    p: Packet, neighbours: list, variant: Literal["random", "nonbacktracking", "lrv"]
) -> str:
    if len(neighbours) == 1:
        return neighbours[0]
    assert len(neighbours) > 1
    if variant == "random":
        return choice(neighbours)
    elif variant == "nonbacktracking":
        if len(p.history) < 2:
            return choice(neighbours)
        prev_node = p.history[-2]
        other_nodes = [n for n in neighbours if n != prev_node]
        if not other_nodes:
            return prev_node
        return choice(other_nodes)
    elif variant == "lrv":
        assert len(p.history) > 0  # it should always contain the source node
        last_idx = {node: i for i, node in enumerate(p.history)}
        unvisited = [n for n in neighbours if n not in last_idx]
        if unvisited:
            return choice(unvisited)
        min_idx = min(last_idx[n] for n in neighbours)
        lrv = [n for n in neighbours if last_idx[n] == min_idx]
        return choice(lrv)
    else:
        raise ValueError(f"Invalid variant: {variant}")


class RelayNetwork:
    """Bidirected graph representing a QKD relay network."""

    def __init__(
        self,
        node_list_csv: str,
        edge_list_csv: str,
        config: SimConfig | None = None,
    ):
        if config is None:
            config = SimConfig()
        self.config = config
        
        # Store paths for multiprocessing (workers recreate graph from CSV)
        self._nodes_csv = node_list_csv
        self._edges_csv = edge_list_csv
        
        self.nodes: dict = {}
        self.adj_list: dict = defaultdict(list)
        self.edges: dict = {}
        self._node_ids: list = []
        self._edge_pairs: list = []

        with open(node_list_csv, "r") as file:
            reader = csv.DictReader(file)
            for row in reader:
                node_id = row.get("Id") or row.get("ID") or row.get("id")
                if not node_id:
                    raise ValueError("Node CSV missing Id column")
                self.nodes[node_id] = Node(node_id, config.node_buff_keys)
                self._node_ids.append(node_id)

        with open(edge_list_csv, "r") as file:
            reader = csv.DictReader(file)
            for row in reader:
                src, tgt = row["Source"], row["Target"]
                if src not in self.nodes:
                    self.nodes[src] = Node(src, config.node_buff_keys)
                    self._node_ids.append(src)
                if tgt not in self.nodes:
                    self.nodes[tgt] = Node(tgt, config.node_buff_keys)
                    self._node_ids.append(tgt)
                self.adj_list[src].append(tgt)
                self.adj_list[tgt].append(src)
                key = (min(src, tgt), max(src, tgt))
                if key not in self.edges:
                    self.edges[key] = Link(
                        src, tgt, config.qkd_skr, config.latency,
                        config.link_buff_bits, config.links_empty_at_start
                    )
                    self._edge_pairs.append((src, tgt))

    def get_node(self, id: str) -> Node:
        return self.nodes[id]

    def get_edge(self, src: str, tgt: str) -> Link:
        return self.edges[(min(src, tgt), max(src, tgt))]

    def get_neighbours(self, id: str) -> list:
        return self.adj_list[id]

    def node_ids(self) -> list:
        return list(self._node_ids)

    def reset(self) -> None:
        cfg = self.config
        self.nodes = {
            node_id: Node(node_id, cfg.node_buff_keys) for node_id in self._node_ids
        }
        self.adj_list = defaultdict(list)
        self.edges = {}
        for src, tgt in self._edge_pairs:
            self.adj_list[src].append(tgt)
            self.adj_list[tgt].append(src)
            key = (min(src, tgt), max(src, tgt))
            if key not in self.edges:
                self.edges[key] = Link(
                    src, tgt, cfg.qkd_skr, cfg.latency,
                    cfg.link_buff_bits, cfg.links_empty_at_start
                )


def simulate_single_pair(
    graph: RelayNetwork,
    S: str,
    T: str,
    sim_duration: float | None = None,
    variant: Literal["random", "nonbacktracking", "lrv"] = "random",
    max_packets: int | None = None,
) -> list:
    """
    Simulate packet transmission from S to T.
    Stop when sim_duration is exceeded OR max_packets are gathered (whichever comes first).
    At least one of sim_duration or max_packets must be provided.
    Returns list of Packet objects.
    """
    if sim_duration is None and max_packets is None:
        raise ValueError("At least one of sim_duration or max_packets must be provided")

    cfg = graph.config
    events = []
    nodes = graph.nodes

    for _ in range(cfg.node_buff_keys):
        new_packet = Packet(history=[S], started_at=0.0, finished_at=None)
        chosen_neighbour = choose_next(new_packet, graph.get_neighbours(S), variant)
        waiting_time = graph.get_edge(S, chosen_neighbour).reserve(0.0, cfg.key_size)
        nodes[S].buffer_space -= 1
        push(
            events,
            (0.0 + waiting_time, ("link_ready", S, chosen_neighbour, new_packet)),
        )

    # packets with arrival times and history
    arrived_packets: list = []

    while events:  # non-decreasing time event loop
        time, e = pop(events)
        if sim_duration is not None and time > sim_duration:
            break
        if max_packets is not None and len(arrived_packets) >= max_packets:
            break

        et = e[0]  # event type
        p: Packet = e[3]  # packet

        if et == "link_ready":  # self-notification that material is retrieved
            me, neighbour = e[1], e[2]
            push(events, (time + cfg.latency, ("rcv_ready", me, neighbour, p)))
        elif et == "rcv_ready":  # sender received OTP key material from link
            # now we have to ensure that buffer has enough space
            # if not, append to waiting list of this node
            src, me = e[1], e[2]
            if nodes[me].buffer_space > 0:  # buffer has space for key
                nodes[me].buffer_space -= 1
                push(events, (time + cfg.latency, ("rcv_can_send", me, src, p)))
            else:
                nodes[me].waiting.append((src, p))

        elif et == "rcv_can_send":
            me, target = e[2], e[1]
            push(events, (time + cfg.latency, ("rcv_key", me, target, p)))
            nodes[me].buffer_space += 1

            if nodes[me].waiting:
                next_waiting, next_packet = nodes[me].waiting.pop(0)
                nodes[me].buffer_space -= 1
                push(
                    events,
                    (time + cfg.latency, ("rcv_can_send", me, next_waiting, next_packet)),
                )
            elif me == S:
                new_packet = Packet(history=[S], started_at=time, finished_at=None)
                chosen_neighbour = choose_next(
                    new_packet, graph.get_neighbours(S), variant
                )
                nodes[S].buffer_space -= 1
                waiting_time = graph.get_edge(S, chosen_neighbour).reserve(
                    time, cfg.key_size
                )
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
                    push(events, (time + cfg.latency, ("rcv_can_send", T, next_waiting)))
            else:
                me = tgt
                chosen_neighbour = choose_next(p, graph.get_neighbours(me), variant)
                waiting_time = graph.get_edge(me, chosen_neighbour).reserve(
                    time, cfg.key_size
                )
                push(
                    events,
                    (time + waiting_time, ("link_ready", me, chosen_neighbour, p)),
                )

    return arrived_packets


@dataclass
class SimulationResult:
    """Result of a single simulation run (raw data only, metadata in config.json)."""
    arrival_times: list  # list[float]
    packets: list  # list[dict] - serialized Packet objects
    
    def to_dict(self) -> dict:
        return {
            "arrival_times": self.arrival_times,
            "packets": self.packets,
        }
    
    @classmethod
    def from_dict(cls, d: dict) -> "SimulationResult":
        return cls(
            arrival_times=d["arrival_times"],
            packets=d["packets"],
        )
    
    def save(self, filepath: str) -> None:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(self.to_dict(), f, indent=2)
    
    @classmethod
    def load(cls, filepath: str) -> "SimulationResult":
        with open(filepath, "r") as f:
            return cls.from_dict(json.load(f))


def run_simulation(
    graph: RelayNetwork,
    source: str,
    target: str,
    variant: Literal["random", "nonbacktracking", "lrv"],
    graph_name: str,
) -> tuple[SimulationResult, dict]:
    """Run a simulation and return the result and config metadata."""
    graph.reset()
    arrived_packets = simulate_single_pair(
        graph, source, target, graph.config.sim_duration, variant=variant
    )
    
    arrival_times = [p.finished_at for p in arrived_packets if p.finished_at is not None]
    packets = [p.to_dict() for p in arrived_packets]
    
    result = SimulationResult(
        arrival_times=arrival_times,
        packets=packets,
    )
    
    config = {
        "graph": graph_name,
        "source": source,
        "target": target,
        "variant": variant,
        "nodes_count": len(graph.nodes),
        "edges_count": len(graph.edges),
        **graph.config.to_dict(),
    }
    
    return result, config


def _pairwise_worker(args: tuple) -> dict:
    """Worker function for parallel pairwise simulation."""
    nodes_csv, edges_csv, src, tgt, variant, sim_duration, config_dict = args
    
    config = SimConfig.from_dict(config_dict)
    graph = RelayNetwork(nodes_csv, edges_csv, config=config)
    
    arrived = simulate_single_pair(
        graph, src, tgt, sim_duration=sim_duration, variant=variant
    )
    
    if arrived:
        last_arrival = max(p.finished_at for p in arrived if p.finished_at)
        keys_per_sec = len(arrived) / last_arrival if last_arrival > 0 else 0
        throughput_kbps = (keys_per_sec * config.key_size) / 1000
        hop_counts = [len(p.history) - 1 for p in arrived]
        mean_hops = sum(hop_counts) / len(hop_counts)
    else:
        throughput_kbps = 0
        mean_hops = float('nan')
    
    return {
        "source": src,
        "target": tgt,
        "throughput_kbps": throughput_kbps,
        "mean_hops": mean_hops,
        "packets": len(arrived),
        "packet_data": [p.to_dict() for p in arrived],
    }


def run_pairwise_simulations(
    graph: RelayNetwork,
    selected_nodes: list,
    variant: Literal["random", "nonbacktracking", "lrv"],
    sim_duration: float,
    graph_name: str,
    parallel: bool = True,
    num_workers: int | None = None,
) -> list:
    """
    Run simulations for all pairs of selected nodes.
    Returns list of dicts with results.
    
    Args:
        parallel: If True, use multiprocessing (default True)
        num_workers: Number of worker processes (default: CPU count)
    """
    # Build list of tasks
    tasks = []
    for src in selected_nodes:
        for tgt in selected_nodes:
            if src != tgt:
                tasks.append((
                    graph._nodes_csv, graph._edges_csv,
                    src, tgt, variant, sim_duration,
                    graph.config.to_dict()
                ))
    
    total_pairs = len(tasks)
    
    if parallel and total_pairs > 1:
        import multiprocessing as mp
        if num_workers is None:
            num_workers = mp.cpu_count()
        
        print(f"  Running {total_pairs} pairs with {num_workers} workers...")
        results = []
        with mp.Pool(num_workers) as pool:
            for i, result in enumerate(pool.imap_unordered(_pairwise_worker, tasks)):
                results.append(result)
                print(f"  [{i+1}/{total_pairs}] {result['source']} -> {result['target']}: "
                      f"{result['throughput_kbps']:.2f} kbit/s, {result['mean_hops']:.1f} hops "
                      f"({result['packets']} packets)")
        return results
    else:
        # Sequential fallback
        results = []
        for i, task in enumerate(tasks):
            result = _pairwise_worker(task)
            results.append(result)
            print(f"  [{i+1}/{total_pairs}] {result['source']} -> {result['target']}: "
                  f"{result['throughput_kbps']:.2f} kbit/s, {result['mean_hops']:.1f} hops "
                  f"({result['packets']} packets)")
        return results


def _hop_worker(args: tuple) -> dict:
    """Worker function for parallel hop analysis."""
    nodes_csv, edges_csv, source, dest, variant, sim_duration, config_dict = args
    
    config = SimConfig.from_dict(config_dict)
    graph = RelayNetwork(nodes_csv, edges_csv, config=config)
    
    arrived = simulate_single_pair(
        graph, source, dest, sim_duration=sim_duration, variant=variant
    )
    
    if arrived:
        hop_counts = [len(p.history) - 1 for p in arrived]
        mean_hops = sum(hop_counts) / len(hop_counts)
        min_hops = min(hop_counts)
        max_hops = max(hop_counts)
        std_hops = (sum((h - mean_hops) ** 2 for h in hop_counts) / len(hop_counts)) ** 0.5
    else:
        mean_hops = float('nan')
        min_hops = 0
        max_hops = 0
        std_hops = 0
    
    return {
        "source": source,
        "destination": dest,
        "mean_hops": mean_hops,
        "min_hops": min_hops,
        "max_hops": max_hops,
        "std_hops": std_hops,
        "packets": len(arrived),
    }


def run_hop_analysis(
    graph: RelayNetwork,
    source: str,
    variant: Literal["random", "nonbacktracking", "lrv"],
    sim_duration: float,
    parallel: bool = True,
    num_workers: int | None = None,
) -> list:
    """
    Analyze hop counts from a fixed source to all destinations.
    Returns list of dicts with results.
    
    Args:
        parallel: If True, use multiprocessing (default True)
        num_workers: Number of worker processes (default: CPU count)
    """
    destinations = [n for n in graph.node_ids() if n != source]
    
    tasks = [
        (graph._nodes_csv, graph._edges_csv, source, dest, variant, 
         sim_duration, graph.config.to_dict())
        for dest in destinations
    ]
    
    total = len(tasks)
    
    if parallel and total > 1:
        import multiprocessing as mp
        if num_workers is None:
            num_workers = mp.cpu_count()
        
        print(f"  Running {total} destinations with {num_workers} workers...")
        results = []
        with mp.Pool(num_workers) as pool:
            for i, result in enumerate(pool.imap_unordered(_hop_worker, tasks)):
                results.append(result)
                print(f"  [{i+1}/{total}] {source} -> {result['destination']}: "
                      f"{result['mean_hops']:.1f} hops (min={result['min_hops']}, "
                      f"max={result['max_hops']}, n={result['packets']})")
        return results
    else:
        results = []
        for i, task in enumerate(tasks):
            result = _hop_worker(task)
            results.append(result)
            print(f"  [{i+1}/{total}] {source} -> {result['destination']}: "
                  f"{result['mean_hops']:.1f} hops (min={result['min_hops']}, "
                  f"max={result['max_hops']}, n={result['packets']})")
        return results


def run_edge_node_visit_analysis(
    graph: RelayNetwork,
    source: str,
    target: str,
    variant: Literal["random", "nonbacktracking", "lrv"],
    sim_duration: float,
) -> dict:
    """
    Analyze edge multiplicity and node hitting probability for a specific (source, target) pair.
    Returns dict with edge_multiplicity and node_hitting_prob.
    """
    from collections import Counter
    
    print(f"  {source} -> {target}...", end=" ", flush=True)
    
    graph.reset()
    arrived = simulate_single_pair(
        graph, source, target, sim_duration=sim_duration, variant=variant
    )
    
    total_packets = len(arrived)
    edge_visit_counts = Counter()
    node_hit_counts = Counter()
    
    for p in arrived:
        visited_nodes = set()
        for k in range(len(p.history) - 1):
            edge = tuple(sorted([p.history[k], p.history[k + 1]]))
            edge_visit_counts[edge] += 1
        for node in p.history:
            if node != source and node != target:
                visited_nodes.add(node)
        for node in visited_nodes:
            node_hit_counts[node] += 1
    
    print(f"{total_packets} packets")
    
    if total_packets == 0:
        return {
            "total_packets": 0,
            "edge_multiplicity": {},
            "node_hitting_prob": {},
        }
    
    edge_multiplicity = {f"{e[0]}-{e[1]}": c / total_packets for e, c in edge_visit_counts.items()}
    node_hitting_prob = {n: c / total_packets for n, c in node_hit_counts.items()}
    
    return {
        "total_packets": total_packets,
        "edge_multiplicity": edge_multiplicity,
        "node_hitting_prob": node_hitting_prob,
    }


def _hitting_worker(args: tuple) -> dict:
    """Worker function for parallel hitting heatmap analysis."""
    from collections import Counter
    
    nodes_csv, edges_csv, src, tgt, variant, sim_duration, config_dict = args
    
    config = SimConfig.from_dict(config_dict)
    graph = RelayNetwork(nodes_csv, edges_csv, config=config)
    
    arrived = simulate_single_pair(
        graph, src, tgt, sim_duration=sim_duration, variant=variant
    )
    
    if not arrived:
        return {
            "source": src,
            "target": tgt,
            "max_hitting_node": "",
            "max_hitting_prob": float('nan'),
            "packets": 0,
        }
    
    node_hit_counts = Counter()
    for p in arrived:
        visited = set(p.history)
        for node in visited:
            if node != src and node != tgt:
                node_hit_counts[node] += 1
    
    if node_hit_counts:
        best_node = max(node_hit_counts.keys(), key=lambda n: node_hit_counts[n])
        best_prob = node_hit_counts[best_node] / len(arrived)
    else:
        best_node = "-"
        best_prob = 0
    
    return {
        "source": src,
        "target": tgt,
        "max_hitting_node": best_node,
        "max_hitting_prob": best_prob,
        "packets": len(arrived),
    }


def run_hitting_heatmap_analysis(
    graph: RelayNetwork,
    selected_nodes: list,
    variant: Literal["random", "nonbacktracking", "lrv"],
    sim_duration: float,
    parallel: bool = True,
    num_workers: int | None = None,
) -> list:
    """
    For each pair (s, t), find the intermediate node v with highest hitting probability.
    Returns list of dicts with results.
    
    Args:
        parallel: If True, use multiprocessing (default True)
        num_workers: Number of worker processes (default: CPU count)
    """
    tasks = []
    for src in selected_nodes:
        for tgt in selected_nodes:
            if src != tgt:
                tasks.append((
                    graph._nodes_csv, graph._edges_csv,
                    src, tgt, variant, sim_duration,
                    graph.config.to_dict()
                ))
    
    total_pairs = len(tasks)
    
    if parallel and total_pairs > 1:
        import multiprocessing as mp
        if num_workers is None:
            num_workers = mp.cpu_count()
        
        print(f"  Running {total_pairs} pairs with {num_workers} workers...")
        results = []
        with mp.Pool(num_workers) as pool:
            for i, result in enumerate(pool.imap_unordered(_hitting_worker, tasks)):
                results.append(result)
                if result['packets'] == 0:
                    print(f"  [{i+1}/{total_pairs}] {result['source']} -> {result['target']}: no packets")
                else:
                    print(f"  [{i+1}/{total_pairs}] {result['source']} -> {result['target']}: "
                          f"{result['max_hitting_node']} ({result['max_hitting_prob']:.2f})")
        return results
    else:
        results = []
        for i, task in enumerate(tasks):
            result = _hitting_worker(task)
            results.append(result)
            if result['packets'] == 0:
                print(f"  [{i+1}/{total_pairs}] {result['source']} -> {result['target']}: no packets")
            else:
                print(f"  [{i+1}/{total_pairs}] {result['source']} -> {result['target']}: "
                      f"{result['max_hitting_node']} ({result['max_hitting_prob']:.2f})")
        return results


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

# Fixed (source, target) pairs for main throughput analysis
GRAPH_PAIRS = {
    "geant": ("MIL", "COP"),
    "nsfnet": ("BOU", "PIT"),
    "secoqc": ("BRE", "SIE"),
}


if __name__ == "__main__":
    # Simple test
    print("Testing simulate.py...")
    cfg = SimConfig(sim_duration=10.0)
    graph = RelayNetwork(
        "graphs/geant/geant_nodes.csv",
        "graphs/geant/geant_edges.csv",
        config=cfg,
    )
    packets = simulate_single_pair(graph, "MIL", "COP", sim_duration=10.0, variant="nonbacktracking")
    print(f"Simulated {len(packets)} packets in 10s")
