# script count vertices and edges; assert undirected graph; no self-loops

from collections import defaultdict
import csv
import sys

if len(sys.argv) != 3:
    print("Usage: python count.py <nodes.csv> <edges.csv>")
    sys.exit(1)

nodes_file = sys.argv[1]
edges_file = sys.argv[2]

# read nodes
nodes = set()
with open(nodes_file, 'r') as file:
    reader = csv.DictReader(file)
    for row in reader:
        nodes.add(row['Id'])

# read edges
edge_count = 0
adj = defaultdict[str, list[str]](list)
self_loops = False
with open(edges_file, 'r') as file:
    reader = csv.DictReader(file)
    for row in reader:
        src, tgt = row['Source'], row['Target']
        if src == tgt:
            print(f"found self-loop {src}")
            self_loops = True
            continue
        if src not in nodes:
            print(f"node {src} not in nodes file")
        if tgt not in nodes:
            print(f"node {tgt} not in nodes file")
        adj[src].append(tgt)
        adj[tgt].append(src)
        edge_count += 1
if not self_loops:
    print(f"no self-loops")

directed = False
duplicate_edges = False
for node in adj:
    for neighbor in adj[node]:
        if node not in adj[neighbor]:
            print(f"found directed edge {node} -> {neighbor}")
            directed = True
        if adj[node].count(neighbor) > 1:
            print(f"found duplicate edge {node} -> {neighbor}")
            duplicate_edges = True
if not directed:
    print(f"graph is undirected")
if not duplicate_edges:
    print(f"no duplicate edges")

# compute degrees
degrees = {node: len(adj[node]) for node in adj}
isolated = [n for n in nodes if n not in adj]
degree_1 = sorted([n for n, d in degrees.items() if d == 1])

print(f"vertices: {len(nodes)}, edges: {edge_count}")
if isolated:
    print(f"isolated nodes (degree 0): {sorted(isolated)}")
else:
    print(f"no isolated nodes")

# print degrees
for (node, degree) in degrees.items():
    print(f"{node}: {degree}")