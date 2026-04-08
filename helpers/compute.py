import networkx as nx
import subprocess
import ast
from dataclasses import dataclass, field
from typing import Literal

# random walk variants
VARS = Literal["R", "NB", "LRV", "NC", "HS"]

@dataclass
class HopSimParams:
    g: nx.Graph
    src: str
    tgt: str  # no that the order of src and tgt IS important
    var: VARS  # random walk variant
    no_of_runs: int
    erase_loops: bool = False
    record_paths: bool = False
    
@dataclass
class HopStats:
    context: HopSimParams
    min_hops: int
    max_hops: int
    mean_hops: float
    q1_hops: int
    q2_hops: int # median
    q3_hops: int
    exposure: float
    exposure_relay: str
    paths: list[list[str]] = field(default_factory=list)

    def print(self):
        src, tgt, var = self.context.src, self.context.tgt, self.context.var
        print(f"{src} -> {tgt} ({var}):", end=" ")
        print(f"exposure={self.exposure_relay},{self.exposure:.3f}", end=" ")
        print(f"min={self.min_hops}", end=" ")
        print(f"mean={self.mean_hops:.3f}", end=" ")
        print(f"max={self.max_hops}", end=" ")
        print(f"q1={self.q1_hops}", end=" ")
        print(f"q2={self.q2_hops}", end=" ")
        print(f"q3={self.q3_hops}")

@dataclass
class TputSimParams:
    g: nx.Graph
    src: str
    tgt: str  # no that the order of src and tgt IS important
    var: VARS  # random walk variant
    erase_loops: bool = False

    chunk_size_bits: int = 256
    link_buff_sz_bits: int = 100000
    qkd_skr_bits_per_s: float = 1000.0
    latency_s: float = 0.05
    sim_duration_s: float = 1000.0
    relay_buffer_sz_chunks: int = 100000
    print_arrival_times: bool = False

@dataclass
class ThroughputStats:
    context: TputSimParams
    mean_tput_bits: int  # bits/s
    arrival_times: list[float] # timestamps
    emitted_chunks: int  # may have not arrived yet

built_hops_bin = False
def compute_hop_stats(params: HopStats.HopSimParams) -> HopStats:
    global built_hops_bin
    if not built_hops_bin:
        subprocess.run(["make", "build/hops"], stdout=subprocess.DEVNULL, cwd="cpp")
        built_hops_bin = True
    src = str(params.src)
    tgt = str(params.tgt)
    stdin_str = f"{params.g.number_of_nodes()} {params.g.number_of_edges()}\n"
    for edge in params.g.edges():
        stdin_str += f"{edge[0]} {edge[1]}\n"
    cmd = [
        "./cpp/build/hops",
        "--src-node",
        src,
        "--tgt-node",
        tgt,
        "--rw-variant",
        params.var,
        "--no-of-runs",
        str(params.no_of_runs),
    ]
    if params.erase_loops:
        cmd.append("--erase-loops")
    if params.record_paths:
        cmd.append("--record-paths")

    result = subprocess.run(
        cmd,
        input=stdin_str,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Exception(f"Failed to compute hop stats: {result.returncode} {result.stderr}")
    recorded_paths: list[list[str]] = []
    for line in result.stdout.split("\n"):
        if line == "": break
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key == "context": assert value==f"{params.src} -> {params.tgt} ({params.var}, {params.no_of_runs} runs)"
        elif key == "min_hops": min_hops = int(value)
        elif key == "max_hops": max_hops = int(value)
        elif key == "mean_hops": mean_hops = float(value)
        elif key == "q1_hops": q1_hops = int(value)
        elif key == "q2_hops": q2_hops = int(value)
        elif key == "q3_hops": q3_hops = int(value)
        elif key == "max_hit_prob": max_hit_prob = float(value)
        elif key == "max_hit_node": max_hit_node = value
        elif key == "path_count": recorded_paths = []
        elif key.startswith("path "): recorded_paths.append(value.split())
    return HopStats(
        context=params,
        min_hops=min_hops,
        max_hops=max_hops,
        mean_hops=mean_hops,
        q1_hops=q1_hops,
        q2_hops=q2_hops,
        q3_hops=q3_hops,
        exposure=max_hit_prob,
        exposure_relay=max_hit_node,
        paths=recorded_paths,
    )


def compute_tput_stats(params: ThroughputStats.TputSimParams) -> ThroughputStats:
    subprocess.run(["make", "build/tput"], stdout=subprocess.DEVNULL, cwd="cpp")
    src = params.src
    tgt = params.tgt
    stdin_str = f"{params.g.number_of_nodes()} {params.g.number_of_edges()}\n"
    for edge in params.g.edges():
        stdin_str += f"{edge[0]} {edge[1]}\n"

    cmd = [
        "./cpp/build/tput",
        "--src-node",
        str(src),
        "--tgt-node",
        str(tgt),
        "--rw-variant",
        params.var,
        "--chunk-size-bits",
        str(params.chunk_size_bits),
        "--link-buff-sz-bits",
        str(params.link_buff_sz_bits),
        "--qkd-skr-bits-per-s",
        str(params.qkd_skr_bits_per_s),
        "--latency-s",
        str(params.latency_s),
        "--sim-duration-s",
        str(params.sim_duration_s),
        "--relay-buffer-sz-chunks",
        str(params.relay_buffer_sz_chunks),
    ]
    if params.erase_loops:
        cmd.append("--erase-loops")
    if params.print_arrival_times:
        cmd.append("--print-arrival-times")

    result = subprocess.run(
        cmd,
        input=stdin_str,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Exception(f"Failed to compute throughput stats: {result.stderr}")

    mean_tput_bits = 0
    emitted_chunks = 0
    arrival_times: list[float] = []
    for line in result.stdout.split("\n"):
        if line == "":
            break
        key = line.split(":")[0].strip()
        value = line.split(":", 1)[1].strip()
        if key == "mean_tput_bits":
            mean_tput_bits = int(value)
        elif key == "emitted_chunks":
            emitted_chunks = int(value)
        elif key == "arrival_times":
            parsed = ast.literal_eval(value)
            arrival_times = [float(ts) for ts in parsed]

    return ThroughputStats(
        context=params,
        mean_tput_bits=mean_tput_bits,
        arrival_times=arrival_times,
        emitted_chunks=emitted_chunks,
    )