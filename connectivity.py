import networkx as nx
import polars as pl
import sys
import csv
from pathlib import Path

if len(sys.argv) < 3:
    print(f"Usage: {sys.argv[0]} <edge_list.csv> <out_dir>", file=sys.stderr)
    sys.exit(2)

edges_csv = pl.read_csv(sys.argv[1])
out_dir = Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)
edge_list = edges_csv.select(["Source", "Target"]).rows()
nodes = {edge[0] for edge in edge_list} | {edge[1] for edge in edge_list}
G = nx.Graph(edge_list)
out_csv = open(out_dir / "connectivity.csv", "w")
writer = csv.writer(out_csv)
writer.writerow(["source", "target", "connectivity"])
for source in nodes:
    for target in nodes:
        if source >= target: continue
        nc = nx.node_connectivity(G, source, target)
        writer.writerow([source, target, nc])