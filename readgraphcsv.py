import csv
from dataclasses import dataclass, field
from pathlib import Path
import sys
from typing import Any, Literal

import networkx as nx
import polars as pl


# this graph is unweighted
@dataclass
class Graph:
    """Adjacency-list graph. node_names[i] is the label of node i (optional)."""
    adj_list: list[list[int]]
    node_names: list | None = None
    _cache: dict = field(default_factory=dict, repr=False, compare=False)

    def __getstate__(self) -> dict:
        return {'adj_list': self.adj_list, 'node_names': self.node_names}

    def __setstate__(self, state: dict) -> None:
        self.adj_list = state['adj_list']
        self.node_names = state.get('node_names')
        self._cache = {}

    @classmethod
    def from_nx(cls, g: nx.Graph) -> 'Graph':
        nodes = list(g.nodes())
        node_to_idx = {v: i for i, v in enumerate(nodes)}
        adj_list = [[node_to_idx[u] for u in g.neighbors(v)] for v in nodes]
        return cls(adj_list=adj_list, node_names=nodes)
    
    def to_nx(self) -> nx.Graph:
        g = nx.Graph()
        g.add_nodes_from(range(len(self.adj_list)))
        for u, neighbors in enumerate(self.adj_list):
            for v in neighbors:
                g.add_edge(u, v)
        return g


def _repo_root_from_file() -> Path:
    current_dir = Path(__file__).resolve().parent
    for candidate in (current_dir, *current_dir.parents):
        if (candidate / ".git").exists():
            return candidate
    raise FileNotFoundError(f"Could not locate git repo root from {__file__}")


def read_graph(graph_name: Literal["geant", "nsfnet", "secoqc"], graphs_dir: Path | None = None) -> Graph:
    base_dir = graphs_dir if graphs_dir is not None else _repo_root_from_file() / "graphs"
    return Graph.from_nx(_read_graph_from_edges_csv(base_dir / graph_name / "edges.csv"))


def synthetic_graph_snapshot(nodes: int, graphs_dir: Path | None = None) -> Graph:
    if nodes < 1 or nodes > 99:
        raise ValueError("nodes must be between 1 and 99")
    if nodes % 3 != 0:
        print("Warning: synthetic graph snapshot may be malformed!", file=sys.stderr)

    base_dir = graphs_dir if graphs_dir is not None else _repo_root_from_file() / "graphs"
    edge_list = pl.read_csv(base_dir / "generated" / "edges.csv")
    di_graph = nx.DiGraph(edge_list.select(["Source", "Target"]).rows())
    for edge in list(di_graph.edges()):
        if edge[0] > nodes:
            di_graph.remove_edge(edge[0], edge[1])
    isolated_nodes = list(nx.isolates(di_graph))
    di_graph.remove_nodes_from(isolated_nodes)
    return Graph.from_nx(nx.Graph(di_graph))


def _coerce_csv_value(value: str) -> Any:
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _read_graph_from_edges_csv(edges_csv: Path) -> nx.Graph:
    graph = nx.Graph()
    with edges_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"Missing CSV header in {edges_csv}")
        required_fields = {"Source", "Target"}
        missing_fields = required_fields - set(reader.fieldnames)
        if missing_fields:
            missing = ", ".join(sorted(missing_fields))
            raise ValueError(f"Missing required columns in {edges_csv}: {missing}")

        for row in reader:
            src = row["Source"]
            tgt = row["Target"]
            attrs = {
                key: _coerce_csv_value(value)
                for key, value in row.items()
                if key not in required_fields and value not in (None, "")
            }
            graph.add_edge(src, tgt, **attrs)
    return graph
