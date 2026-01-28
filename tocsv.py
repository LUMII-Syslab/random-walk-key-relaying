from collections import defaultdict
import csv

# this scripts convert adj list in proprietary format to csv
in_file = 'geant.txt'
edge_out_f = 'geant_edges.csv'
node_out_f = 'geant_nodes.csv'

res = 0
adj = defaultdict[str, list[str]](list)
with open(in_file, 'r') as file:
    for line in file.readlines():
        line = line.strip()
        if len(line.split(': ')) != 2:
            if line != '':
                print(f"skipping {line}")
            continue
        left = line.split(': ')[0]
        right = line.split(': ')[1]
        res += len(right.split(' '))
        for node in right.split(' '):
            adj[left].append(node)
        if len(set(right.split(' '))) != len(right.split(' ')):
            print(f"found duplicate nodes in {line}")
edge_list = set()
for node in adj:
    for neighbor in adj[node]:
        fst, snd = sorted([node, neighbor])
        edge_list.add((fst, snd))

with open(edge_out_f, 'w') as file:
    writer = csv.writer(file)
    writer.writerow(['Source', 'Target'])
    for edge in edge_list:
        writer.writerow(edge)

node_set = set()
for node in adj:
    node_set.add(node)
    for neighbor in adj[node]:
        node_set.add(neighbor)

# with open(node_out_f, 'w') as file:
#     writer = csv.writer(file)
#     writer.writerow(['Id', 'Label', 'Latitude', 'Longitude'])
#     for node in adj:
#         writer.writerow([node, '?', '?', '?'])