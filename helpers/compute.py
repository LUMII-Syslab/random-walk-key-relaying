"""
Helper module to build and call C++ simulations for
computing fixed source-target hop trajectory and throughput statistics.
"""

import math
import networkx as nx
import subprocess
import ast
from dataclasses import dataclass, field
from typing import Literal, Optional, Union

# random walk variants
RW_VARIANTS = Literal["R", "NB", "LRV", "NC", "HS"]


@dataclass
class HopSimParams:
    g: nx.Graph
    src: str
    tgt: str  # no that the order of src and tgt IS important
    var: RW_VARIANTS  # random walk variant
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
    q2_hops: int  # median
    q3_hops: int
    exposure: float
    exposure_relay: str
    paths: list[list[str]] = field(default_factory=list)

    def print_summary(self):
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
    var: RW_VARIANTS  # random walk variant
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
    arrival_times: list[float]  # timestamps
    emitted_chunks: int  # may have not arrived yet


@dataclass
class ProactiveSimParams:
    """
    Proactive simulation assumes:
    - chunk size is fixed at 256 bits
    - qkd skr (secret key rate) is fixed at 1000 bits/s
    - link buffer is unlimited but starts at empty
    - classic network latency is fixed at 5 milliseconds
    - node fifo relay buffer is unlimited
    - min ttl is fixed at 1, max ttl is fixed at 100
    """

    g: nx.Graph
    src_nodes: list[str]
    rw_variant: RW_VARIANTS  # random walk variant
    duration_s: float  # simulation duration in seconds
    sieve_table_sz: int = 32
    watermark_sz: int = 16  # the targeted number of buffered keys
    ignore_events: Optional[list[str]] = None  # event kinds, e.g. ["recv_chunk"]


@dataclass
class ProactiveRecvChunkEvent:
    time: float  # timestamp of the event
    src: str  # source node that originated the chunk
    tgt: str  # target node that received the chunk
    path: list[str] = field(default_factory=list)  # if recording is enabled
    type: Literal["recv_chunk"] = "recv_chunk"


@dataclass
class ProactiveKeyEstablishedEvent:
    time: float  # timestamp of the event
    src: str  # node that sent the chunks
    tgt: str  # node that will be sending the feedback puzzle
    key_count: int  # number of established 256 bit keys
    type: Literal["key_establ"] = "key_establ"


ProactiveSimEvent = Union[ProactiveRecvChunkEvent, ProactiveKeyEstablishedEvent]


@dataclass
class ProactiveStats:
    context: ProactiveSimParams
    events: list[ProactiveSimEvent]
    watermark_time: float  # time until watermark was reached from all src nodes

    def print_summary(self):
        p = self.context
        src = ",".join(p.src_nodes)
        print(
            f"proactive {src} ({p.rw_variant}, {p.duration_s}s): "
            f"events={len(self.events)} watermark_time={self.watermark_time}"
        )


built_hops_bin = False
built_proactive_bin = False


def compute_hop_stats(params: HopSimParams) -> HopStats:
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
        raise Exception(
            f"Failed to compute hop stats: {result.returncode} {result.stderr}"
        )
    recorded_paths: list[list[str]] = []
    for line in result.stdout.split("\n"):
        if line == "":
            break
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key == "context":
            assert (
                value
                == f"{params.src} -> {params.tgt} ({params.var}, {params.no_of_runs} runs)"
            )
        elif key == "min_hops":
            min_hops = int(value)
        elif key == "max_hops":
            max_hops = int(value)
        elif key == "mean_hops":
            mean_hops = float(value)
        elif key == "q1_hops":
            q1_hops = int(value)
        elif key == "q2_hops":
            q2_hops = int(value)
        elif key == "q3_hops":
            q3_hops = int(value)
        elif key == "max_hit_prob":
            max_hit_prob = float(value)
        elif key == "max_hit_node":
            max_hit_node = value
        elif key == "path_count":
            recorded_paths = []
        elif key.startswith("path "):
            recorded_paths.append(value.split())
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


def compute_tput_stats(params: TputSimParams) -> ThroughputStats:
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


def compute_proactive_stats(params: ProactiveSimParams) -> ProactiveStats:
    global built_proactive_bin
    if not built_proactive_bin:
        subprocess.run(
            ["make", "build/proactive"], stdout=subprocess.DEVNULL, cwd="cpp"
        )
        built_proactive_bin = True

    stdin_str = f"{params.g.number_of_nodes()} {params.g.number_of_edges()}\n"
    for edge in params.g.edges():
        stdin_str += f"{edge[0]} {edge[1]}\n"

    cmd = [
        "./cpp/build/proactive",
        "--src-nodes",
        ",".join(str(s) for s in params.src_nodes),
        "--rw-variant",
        params.rw_variant,
        "--duration-s",
        str(params.duration_s),
        "--sieve-table-sz",
        str(params.sieve_table_sz),
        "--watermark-sz",
        str(params.watermark_sz),
    ]
    if params.ignore_events:
        cmd += ["--ignore-events", ",".join(params.ignore_events)]

    result = subprocess.run(
        cmd,
        input=stdin_str,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Exception(
            f"Failed to compute proactive stats: {result.returncode} {result.stderr}"
        )

    events: list[ProactiveSimEvent] = []
    watermark_time = 0.0
    expected_src = ",".join(str(s) for s in params.src_nodes)
    expected_event_count: Optional[int] = None

    for line in result.stdout.split("\n"):
        if line == "":
            break
        if ":" in line:
            key, _, rest = line.partition(":")
            key = key.strip()
            value = rest.strip()
            if key == "proactive_version":
                pass
            elif key == "src_nodes":
                if value != expected_src:
                    raise ValueError(
                        f"proactive src_nodes mismatch: {value!r} != {expected_src!r}"
                    )
            elif key == "rw_variant":
                if value != params.rw_variant:
                    raise ValueError(
                        f"proactive rw_variant mismatch: {value!r} != {params.rw_variant!r}"
                    )
            elif key == "duration_s":
                if not math.isclose(
                    float(value), float(params.duration_s), rel_tol=0, abs_tol=1e-9
                ):
                    raise ValueError(
                        f"proactive duration_s mismatch: {value!r} vs params {params.duration_s!r}"
                    )
            elif key == "sieve_table_sz":
                if int(value) != params.sieve_table_sz:
                    raise ValueError("proactive sieve_table_sz mismatch")
            elif key == "watermark_sz":
                if int(value) != params.watermark_sz:
                    raise ValueError("proactive watermark_sz mismatch")
            elif key == "event_count":
                expected_event_count = int(value)
            else:
                raise ValueError(f"unknown proactive output key: {key!r}")
        else:
            parts = line.split()
            if len(parts) < 4:
                raise ValueError(f"bad proactive event line: {line!r}")
            kind = parts[0]
            ev_time = float(parts[1])
            ev_src = parts[2]
            ev_tgt = parts[3]
            if kind == "key_establ":
                if len(parts) != 5:
                    raise ValueError(f"bad key_establ event: {line!r}")
                events.append(
                    ProactiveKeyEstablishedEvent(
                        time=ev_time,
                        src=ev_src,
                        tgt=ev_tgt,
                        key_count=int(parts[4]),
                    )
                )
            elif kind == "recv_chunk":
                path_tokens = parts[4:] if len(parts) > 4 else []
                events.append(
                    ProactiveRecvChunkEvent(
                        time=ev_time,
                        src=ev_src,
                        tgt=ev_tgt,
                        path=list(path_tokens),
                    )
                )
            else:
                raise ValueError(f"unknown proactive event kind: {kind!r}")

    if expected_event_count is not None and expected_event_count != len(events):
        raise ValueError(
            f"proactive event_count {expected_event_count} != parsed {len(events)}"
        )

    # Compute watermark_time in Python:
    # earliest time when for every src in params.src_nodes and every tgt node != src,
    # cumulative established keys for (src,tgt) reaches at least watermark_sz.
    required_pairs: set[tuple[str, str]] = set()
    all_nodes = [str(n) for n in params.g.nodes()]
    for src in (str(s) for s in params.src_nodes):
        for tgt in all_nodes:
            if tgt == src:
                continue
            required_pairs.add((src, tgt))

    counts: dict[tuple[str, str], int] = {}
    remaining = set(required_pairs)
    for ev in events:
        if isinstance(ev, ProactiveKeyEstablishedEvent):
            key = (ev.src, ev.tgt)
            if key in required_pairs:
                counts[key] = counts.get(key, 0) + ev.key_count
                if counts[key] >= params.watermark_sz:
                    remaining.discard(key)
                    if not remaining:
                        watermark_time = float(ev.time)
                        break

    return ProactiveStats(
        context=params,
        events=events,
        watermark_time=watermark_time,
    )
