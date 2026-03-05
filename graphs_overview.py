"""
Generate graph-level overview metrics from edge lists.

Usage:
    python3 graphs_overview.py

This scans graphs/*/edges.csv and writes data/graphs2.csv.
"""

from __future__ import annotations

import csv
from pathlib import Path

import networkx as nx
import polars as pl


ROOT = Path(__file__).resolve().parent
GRAPHS_DIR = ROOT / "graphs"
OUT_CSV = ROOT / "data" / "graphs2.csv"


def format_float(value: float, digits: int) -> str:
    return f"{value:.{digits}f}"


def read_graph(edges_csv: Path) -> nx.Graph:
    edges_df = pl.read_csv(edges_csv)
    edge_rows = edges_df.select(["Source", "Target"]).rows()
    return nx.Graph(edge_rows)


def diameter_and_apl(graph: nx.Graph) -> tuple[float, float]:
    if graph.number_of_nodes() == 0:
        return 0.0, 0.0
    if nx.is_connected(graph):
        return float(nx.diameter(graph)), float(nx.average_shortest_path_length(graph))

    largest_component_nodes = max(nx.connected_components(graph), key=len)
    component = graph.subgraph(largest_component_nodes).copy()
    return float(nx.diameter(component)), float(nx.average_shortest_path_length(component))


def biconnected_core_fraction(graph: nx.Graph) -> float:
    node_count = graph.number_of_nodes()
    if node_count == 0:
        return 0.0
    components = list(nx.biconnected_components(graph))
    if not components:
        return 0.0
    largest_component = max((len(comp) for comp in components), default=0)
    return largest_component / node_count


def max_betweenness(graph: nx.Graph) -> float:
    if graph.number_of_nodes() == 0:
        return 0.0
    values = nx.betweenness_centrality(graph)
    return float(max(values.values(), default=0.0))


def compute_row(graph_name: str, graph: nx.Graph) -> list[str]:
    node_count = graph.number_of_nodes()
    edge_count = graph.number_of_edges()
    avg_deg = (2.0 * edge_count / node_count) if node_count > 0 else 0.0
    diameter, apl = diameter_and_apl(graph)
    bcc_fraction = biconnected_core_fraction(graph)
    top_betweenness = max_betweenness(graph)

    return [
        graph_name,
        str(node_count),
        str(edge_count),
        str(int(diameter)) if diameter.is_integer() else format_float(diameter, 3),
        format_float(avg_deg, 2),
        format_float(apl, 3),
        format_float(bcc_fraction, 3),
        format_float(top_betweenness, 4),
    ]


def main() -> None:
    edge_files = sorted(GRAPHS_DIR.glob("*/edges.csv"))
    rows = []
    for edge_file in edge_files:
        graph_name = edge_file.parent.name
        graph = read_graph(edge_file)
        rows.append(compute_row(graph_name, graph))

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="") as out_file:
        writer = csv.writer(out_file)
        writer.writerow(
            [
                "graph",
                "nodes",
                "edges",
                "diameter",
                "avg_deg",
                "apl",
                "biconnected_core_fraction",
                "max_betweenness",
            ]
        )
        writer.writerows(rows)

    print(f"Wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
