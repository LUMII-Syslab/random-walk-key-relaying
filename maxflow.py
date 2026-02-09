"""
Calculate the max flow and shortest path for all pairs of nodes in each QKD network graph.
On error, halt.
"""

import sys
import csv
import networkx as nx
import itertools
import os


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
    try:
        flow_value, _ = nx.maximum_flow(D, source, target)
        return flow_value
    except Exception as e:
        print(f"Error computing max flow between {source} and {target}: {e}")
        sys.exit(1)


def compute_shortest_path(G: nx.Graph, source: str, target: str) -> int:
    """Compute shortest path length from source to target."""
    try:
        path = nx.shortest_path(G, source, target)
        length = len(path) - 1  # number of edges
        return length
    except nx.NetworkXNoPath:
        return -1
    except Exception as e:
        print(f"Error computing shortest path between {source} and {target}: {e}")
        sys.exit(1)


def main():
    graphs = [
        ("geant", "graphs/geant/nodes.csv", "graphs/geant/edges.csv"),
        ("nsfnet", "graphs/nsfnet/nodes.csv", "graphs/nsfnet/edges.csv"),
        ("secoqc", "graphs/secoqc/nodes.csv", "graphs/secoqc/edges.csv"),
    ]
    
    for name, nodes_csv, edges_csv in graphs:
        print(f"\n{name.upper()}")
        print("-" * 40)
        
        try:
            G = load_graph(nodes_csv, edges_csv)
        except Exception as e:
            print(f"Error loading graph {name}: {e}")
            sys.exit(1)

        print(f"  Nodes: {G.number_of_nodes()}, Edges: {G.number_of_edges()}")

        node_list = list(G.nodes())
        results = []

        for source, target in itertools.combinations(node_list, 2):
            # Shortest path length only
            shortest = compute_shortest_path(G, source, target)
            # Max flow (number of edge-disjoint paths)
            max_flow = compute_max_flow(G, source, target)
            
            results.append({
                'source': source,
                'target': target,
                'shortest': shortest,
                'max_flow': max_flow
            })

        # Write results to CSV
        outfilename = f"{name}_results.csv"
        with open(outfilename, "w", newline="") as outfile:
            writer = csv.DictWriter(outfile, fieldnames=["source", "target", "shortest", "max_flow"])
            writer.writeheader()
            for r in results:
                writer.writerow(r)
        print(f"  Results written to {outfilename}\n")


if __name__ == "__main__":
    main()
