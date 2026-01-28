# script count vertices and edges; assert undirected graph; no self-loops

from collections import defaultdict
import csv
import sys

if len(sys.argv) != 2:
    print("Usage: python count.py <input_file.csv>")
    sys.exit(1)

in_file = sys.argv[1]

res = 0
adj = defaultdict[str, list[str]](list)
with open(in_file, 'r') as file:
    reader = csv.DictReader(file)
    for row in reader:
        src, tgt = row['Source'], row['Target']
        if src == tgt:
            print(f"found self-loop {src}")
            continue
        adj[src].append(tgt)
        adj[tgt].append(src)
        res += 1

for node in adj:
    for neighbor in adj[node]:
        if node not in adj[neighbor]:
            print(f"found directed edge {node} -> {neighbor}")
        if adj[node].count(neighbor) > 1:
            print(f"found duplicate edge {node} -> {neighbor}")

print(f"vertices: {len(adj)}, edges: {res}")