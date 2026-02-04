"""
Baseline calculations for QKD networks:
- Max flow between source and target
- Shortest path between source and target
"""

import csv
import networkx as nx


def load_graph(nodes_csv: str, edges_csv: str) -> nx.Graph:
    """Load graph from CSV files."""
    G = nx.Graph()
    
    # Load nodes
    with open(nodes_csv, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            node_id = row.get("Id") or row.get("ID") or row.get("id")
            if node_id:
                G.add_node(node_id)
    
    # Load edges (capacity = 1 for max flow)
    with open(edges_csv, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            src, tgt = row["Source"], row["Target"]
            G.add_edge(src, tgt, capacity=1)
    
    return G


def compute_max_flow(G: nx.Graph, source: str, target: str) -> int:
    """Compute max flow from source to target (edge-disjoint paths)."""
    # For undirected graph, convert to directed for max flow
    D = G.to_directed()
    flow_value, _ = nx.maximum_flow(D, source, target)
    return flow_value


def compute_shortest_path(G: nx.Graph, source: str, target: str) -> tuple[list[str], int]:
    """Compute shortest path and its length from source to target."""
    try:
        path = nx.shortest_path(G, source, target)
        length = len(path) - 1  # number of edges
        return path, length
    except nx.NetworkXNoPath:
        return [], -1


def main():
    graphs = [
        ("geant", "graphs/geant/geant_nodes.csv", "graphs/geant/geant_edges.csv", "MIL", "COP"),
        ("nsfnet", "graphs/nsfnet/nsfnet_nodes.csv", "graphs/nsfnet/nsfnet_edges.csv", "BOU", "PIT"),
        ("secoqc", "graphs/secoqc/secoqc_nodes.csv", "graphs/secoqc/secoqc_edges.csv", "BRE", "SIE"),
    ]
    
    for name, nodes_csv, edges_csv, source, target in graphs:
        print(f"\n{name.upper()}: {source} → {target}")
        print("-" * 40)
        
        G = load_graph(nodes_csv, edges_csv)
        print(f"  Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")
        
        # Shortest path
        path, length = compute_shortest_path(G, source, target)
        if path:
            print(f"  Shortest path length: {length} hops")
            print(f"  Shortest path: {' → '.join(path)}")
        else:
            print(f"  No path exists!")
        
        # Max flow (number of edge-disjoint paths)
        max_flow = compute_max_flow(G, source, target)
        print(f"  Max flow (edge-disjoint paths): {max_flow}")
    
    print("\n")


if __name__ == "__main__":
    main()
