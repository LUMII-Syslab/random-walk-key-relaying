from multiprocessing import Value
import networkx as nx
import numpy as np
import subprocess
from dataclasses import dataclass
from collections import Counter
from typing import Literal
from utils import read_edge_list_csv, graphs_dir


def main():
    g = read_edge_list_csv(graphs_dir / "geant" / "edges.csv")
    hop_stats = compute_hop_stats(HopStats.HopSimParams(
        g=g,
        src="MAR",
        tgt="TIR",
        var="LRV",
        no_of_runs=1000,
    ))
    hop_stats.print()


# random walk variants
VARS = Literal["R", "NB", "LRV"]

@dataclass
class HopStats:
    @dataclass
    class HopSimParams:
        g: nx.Graph
        src: str
        tgt: str  # no that the order of src and tgt IS important
        var: VARS  # random walk variant
        no_of_runs: int

    context: HopSimParams
    min_hops: int
    max_hops: int
    mean_hops: float
    q1_hops: int
    q2_hops: int # median
    q3_hops: int
    max_hit_prob: float
    max_hit_node: str

    def print(self):
        src, tgt, var = self.context.src, self.context.tgt, self.context.var
        print(f"{src} -> {tgt} ({var}):", end=" ")
        print(f"exposure={self.max_hit_node},{self.max_hit_prob:.3f}", end=" ")
        print(f"min={self.min_hops}", end=" ")
        print(f"mean={self.mean_hops:.3f}", end=" ")
        print(f"max={self.max_hops}", end=" ")
        print(f"q1={self.q1_hops}", end=" ")
        print(f"q2={self.q2_hops}", end=" ")
        print(f"q3={self.q3_hops}")


@dataclass
class ThroughputStats:
    class TputSimParams:
        g: nx.Graph
        src: str
        tgt: str  # no that the order of src and tgt IS important
        var: VARS  # random walk variant

        chunk_size_bits: int = 256
        link_buff_sz_bits: int = 100000
        qkd_skr_bits_per_s: float = 1000.0
        latency_s: float = 0.05
        sim_duration_s: float = 1000.0
        relay_buffer_sz_chunks: int = 100000

    context: TputSimParams
    arrived_chunks: int
    emitted_chunks: int  # may have not arrived yet


@dataclass
class SrcTgtStats(HopStats, ThroughputStats):
    @dataclass
    class Params:
        g: nx.Graph
        src: str
        tgt: str  # tgt > src
        var: VARS  # random walk variant
        rev: bool  # start from target and go to source?

    context: Params

    exposure: float
    mean_tput: float  # = arrived_chunks * chunk_size_bits / sim_duration_s
    max_flow_eff: float  # mean_tput / max_flow
    node_conn_eff: float  # mean_tput*(1-exposure) / (node_conn-1)


# for now exclude from stats:
# - approx_logest: list[str]


def compute_hop_stats(params: HopStats.HopSimParams) -> HopStats:
    subprocess.run(["make", "build/hops"], stdout=subprocess.DEVNULL)
    src = params.src
    tgt = params.tgt
    stdin_str = f"{params.g.number_of_nodes()} {params.g.number_of_edges()}\n"
    for edge in params.g.edges():
        stdin_str += f"{edge[0]} {edge[1]}\n"
    result = subprocess.run(
        [
            "./build/hops",
            "--src-node",
            src,
            "--tgt-node",
            tgt,
            "--rw-variant",
            params.var,
            "--no-of-runs",
            str(params.no_of_runs),
        ],
        input=stdin_str,
        capture_output=True,
        text=True,
    )
    for line in result.stdout.split("\n"):
        if line == "": break
        key = line.split(":")[0].strip()
        value = line.split(":")[1].strip()
        if key == "min_hops": min_hops = int(value)
        elif key == "max_hops": max_hops = int(value)
        elif key == "mean_hops": mean_hops = float(value)
        elif key == "q1_hops": q1_hops = int(value)
        elif key == "q2_hops": q2_hops = int(value)
        elif key == "q3_hops": q3_hops = int(value)
        elif key == "max_hit_prob": max_hit_prob = float(value)
        elif key == "max_hit_node": max_hit_node = value
    return HopStats(
        context=params,
        min_hops=min_hops,
        max_hops=max_hops,
        mean_hops=mean_hops,
        q1_hops=q1_hops,
        q2_hops=q2_hops,
        q3_hops=q3_hops,
        max_hit_prob=max_hit_prob,
        max_hit_node=max_hit_node,
    )

# def compute_src_tgt_stats(params: SrcTgtStats.Params) -> SrcTgtStats:
#     return SrcTgtStats(
#         context=params,
#         hop_stats=compute_hop_stats(params.variant),
#         shortest_path=nx.shortest_path(g, src, tgt),
#         connectivity=nx.node_connectivity(g, src, tgt),
#         hop_stats=compute_hop_stats(variant),
#     )


# def calc_efficiency(src_tgt: SrcTgt, exp: float, tput: float) -> TputEfficiency:
#     max_flow = nx.maximum_flow_value(src_tgt.g, src_tgt.src, src_tgt.tgt)
#     node_conn = nx.node_connectivity(src_tgt.g, src_tgt.src, src_tgt.tgt)
#     return TputEfficiency(
#         max_flow_eff=tput / max_flow,
#         node_conn_eff=tput * (1 - exp) / (node_conn - 1),
#     )

if __name__ == "__main__":
    main()
