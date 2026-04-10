from helpers.graphs import read_geant_graph
from helpers.compute import (
    compute_proactive_stats,
    ProactiveSimParams,
)
import networkx as nx

geant: nx.Graph = read_geant_graph()

IGNORE_EVENTS: list[str] | None = ["recv_chunk"]

def print_proactive_events_pretty(events) -> None:
    if not events:
        print("(no events)")
        return

    for ev in events:
        if getattr(ev, "type", None) == "key_establ":
            print(f"{ev.time:.3f}s key {ev.src}->{ev.tgt} +{ev.key_count}")
        elif getattr(ev, "type", None) == "recv_chunk":
            # Usually filtered out; keep compact if enabled.
            path = getattr(ev, "path", None) or []
            if path:
                print(f"{ev.time:.3f}s chunk {ev.src}->{ev.tgt} ({' '.join(path)})")
            else:
                print(f"{ev.time:.3f}s chunk {ev.src}->{ev.tgt}")
        else:
            print(ev)

proactive_params = ProactiveSimParams(
    g=geant,
    src_nodes=["MIL"],
    duration_s=36000,
    rw_variant="HS",
    sieve_table_sz=32,
    watermark_sz=16,
    ignore_events=IGNORE_EVENTS,
)

proactive_stats = compute_proactive_stats(proactive_params)
proactive_stats.print_summary()
print_proactive_events_pretty(proactive_stats.events)

