from helpers.graphs import read_geant_graph
from helpers.compute import (
    compute_proactive_stats,
    ProactiveSimParams,
)
import networkx as nx

geant: nx.Graph = read_geant_graph()

proactive_params = ProactiveSimParams(
    g=geant,
    src_nodes=["MIL"],
    duration_s=1,
    rw_variant="HS",
    sieve_table_sz=32,
    watermark_sz=16,
    ignore_events=None,
)

proactive_stats = compute_proactive_stats(proactive_params)
proactive_stats.print_summary()
for event in proactive_stats.events:
    event.print_pretty()

