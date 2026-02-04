"""
Baseline calculations for QKD networks:
- Max flow between source and target
- Shortest path between source and target
"""

import csv
from collections import defaultdict, deque


def load_graph(nodes_csv: str, edges_csv: str) -> tuple[set[str], dict[str, list[str]]]:
    """Load graph from CSV files. Returns (nodes, adjacency list)."""
    nodes = set()
    adj = defaultdict(list)
    
    # Load nodes
    with open(nodes_csv, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            node_id = row.get("Id") or row.get("ID") or row.get("id")
            if node_id:
                nodes.add(node_id)
    
    # Load edges (undirected)
    with open(edges_csv, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            src, tgt = row["Source"], row["Target"]
            nodes.add(src)
            nodes.add(tgt)
            adj[src].append(tgt)
            adj[tgt].append(src)
    
    return nodes, adj


def bfs_path(adj: dict[str, list[str]], source: str, target: str, 
             blocked_edges: set[tuple[str, str]]) -> list[str] | None:
    """Find a path from source to target avoiding blocked edges using BFS."""
    if source == target:
        return [source]
    
    visited = {source}
    queue = deque([(source, [source])])
    
    while queue:
        node, path = queue.popleft()
        
        for neighbor in adj[node]:
            edge = tuple(sorted([node, neighbor]))
            if neighbor not in visited and edge not in blocked_edges:
                new_path = path + [neighbor]
                if neighbor == target:
                    return new_path
                visited.add(neighbor)
                queue.append((neighbor, new_path))
    
    return None


def compute_max_flow(adj: dict[str, list[str]], source: str, target: str) -> int:
    """
    Compute max flow from source to target (edge-disjoint paths).
    Uses Ford-Fulkerson with BFS (Edmonds-Karp style).
    """
    blocked_edges: set[tuple[str, str]] = set()
    flow = 0
    
    while True:
        path = bfs_path(adj, source, target, blocked_edges)
        if path is None:
            break
        
        # Block all edges in this path
        for i in range(len(path) - 1):
            edge = tuple(sorted([path[i], path[i + 1]]))
            blocked_edges.add(edge)
        
        flow += 1
    
    return flow


def compute_shortest_path(adj: dict[str, list[str]], source: str, target: str) -> tuple[list[str], int]:
    """Compute shortest path and its length from source to target using BFS."""
    path = bfs_path(adj, source, target, set())
    if path:
        return path, len(path) - 1
    return [], -1


def count_edges(adj: dict[str, list[str]]) -> int:
    """Count number of edges in undirected graph."""
    return sum(len(neighbors) for neighbors in adj.values()) // 2


def main():
    graphs = [
        ("geant", "graphs/geant/geant_nodes.csv", "graphs/geant/geant_edges.csv", "MIL", "COP"),
        ("nsfnet", "graphs/nsfnet/nsfnet_nodes.csv", "graphs/nsfnet/nsfnet_edges.csv", "BOU", "PIT"),
        ("secoqc", "graphs/secoqc/secoqc_nodes.csv", "graphs/secoqc/secoqc_edges.csv", "BRE", "SIE"),
    ]
    
    print("=" * 70)
    print("BASELINE CALCULATIONS")
    print("=" * 70)
    
    for name, nodes_csv, edges_csv, source, target in graphs:
        print(f"\n{name.upper()}: {source} → {target}")
        print("-" * 40)
        
        nodes, adj = load_graph(nodes_csv, edges_csv)
        print(f"  Nodes: {len(nodes)}, Edges: {count_edges(adj)}")
        
        # Check if source and target exist
        if source not in nodes:
            print(f"  ERROR: Source {source} not in graph!")
            continue
        if target not in nodes:
            print(f"  ERROR: Target {target} not in graph!")
            continue
        
        # Shortest path
        path, length = compute_shortest_path(adj, source, target)
        if path:
            print(f"  Shortest path length: {length} hops")
            print(f"  Shortest path: {' → '.join(path)}")
        else:
            print(f"  No path exists!")
        
        # Max flow (number of edge-disjoint paths)
        max_flow = compute_max_flow(adj, source, target)
        print(f"  Max flow (edge-disjoint paths): {max_flow}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
