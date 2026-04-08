from helpers.graphs import read_geant_graph
from helpers.compute import compute_hop_stats, HopSimParams
import networkx as nx

geant: nx.Graph = read_geant_graph()

SRC, TGT, W = "MAR", "TIR", "HS"

sim_params = HopSimParams(
    g=geant,
    src=SRC,
    tgt=TGT,
    var=W,
    no_of_runs=100,
    erase_loops=False,
    record_paths=True
)

hop_stats = compute_hop_stats(sim_params)
hop_stats.print_summary()

for path in hop_stats.paths:
    print(path)
