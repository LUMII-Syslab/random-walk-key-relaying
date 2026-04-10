from helpers.graphs import read_geant_graph
from helpers.compute import (
    compute_proactive_stats,
    ProactiveSimParams,
)
import networkx as nx

geant: nx.Graph = read_geant_graph()

IGNORE_EVENTS: list[str] | None = ["recv_chunk"]

proactive_params = ProactiveSimParams(
    g=geant,
    src_nodes=["MIL"],
    duration_s=1000,
    rw_variant="HS",
    sieve_table_sz=16,
    watermark_sz=16,
    ignore_events=IGNORE_EVENTS,
)

proactive_stats = compute_proactive_stats(proactive_params)
proactive_stats.print_summary()
for ev in proactive_stats.events:
    print(ev)

