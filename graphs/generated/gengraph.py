import polars as pl
from collections import defaultdict
import random
import csv
random.seed(2026)

def avg_degree(adj):
    bi_adj = defaultdict(set)
    for source, targets in adj.items():
        for target in targets:
            bi_adj[source].add(target)
            bi_adj[target].add(source)
    return sum(len(targets) for targets in bi_adj.values()) / len(bi_adj)

def choose_k(options, k):
    if len(options) < k: raise ValueError(f"Not enough options")
    return random.sample(options, k)

def is_connected(adj, node_count):
    if node_count <= 1:
        return True
    bi_adj = defaultdict(set)
    for source in range(node_count):
        for target in adj[source]:
            if target >= node_count:
                continue
            bi_adj[source].add(target)
            bi_adj[target].add(source)
    visited = set()
    stack = [0]
    while stack:
        node = stack.pop()
        if node in visited:
            continue
        visited.add(node)
        stack.extend(bi_adj[node] - visited)
    return len(visited) == node_count

nodes = 99
coordinates = []
adj = defaultdict[int, list](list)
for i in range(nodes//3):
    x,y=random.random(),random.random()
    x2,y2 = x+random.random()*0.1,y+random.random()*0.1
    x3,y3 = x+random.random()*0.1,y+random.random()*0.1
    coordinates.append((x,y))
    coordinates.append((x2,y2))
    coordinates.append((x3,y3))
    adj[3*i].append(3*i+1)
    adj[3*i+1].append(3*i+2)
    if i == 0: continue
    other_nodes_with_dist = []
    for j in range(i*3):
        dx = coordinates[j][0] - x
        dy = coordinates[j][1] - y
        dist = dx*dx+dy*dy
        other_nodes_with_dist.append((j, dist))
    other_nodes_with_dist.sort(key=lambda x: x[1])
    other_nodes = [x[0] for x in other_nodes_with_dist[:6]]
    other_nodes = random.sample(other_nodes,3)
    adj[3*i].append(other_nodes[0])
    adj[3*i+2].append(other_nodes[1])
    if random.random() < 0.38:
        adj[3*i+1].append(other_nodes[2])
    assert is_connected(adj, 3 * (i + 1)), f"Graph disconnected at step i={i}"
        
print(avg_degree(adj))

with open("generated.csv", "w") as f:
    writer = csv.writer(f)
    writer.writerow(["Source", "Target"])
    edge_list = set()
    for source in range(nodes):
        for target in adj[source]:
            if (source, target) in edge_list: continue
            edge_list.add((source, target))
            edge_list.add((target, source))
    for source, target in sorted(list(edge_list)):
        if source <= target: continue
        writer.writerow([source+1, target+1])