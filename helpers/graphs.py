"""
Helpers for loading the built-in graph topologies shipped with the repo.
"""

from __future__ import annotations

import csv
from pathlib import Path
import sys
from typing import Any, Literal

import networkx as nx
import polars as pl

BuiltinGraphName = Literal["geant", "nsfnet", "secoqc"]


def _repo_root_from_file() -> Path:
    current_dir = Path(__file__).resolve().parent
    for candidate in (current_dir, *current_dir.parents):
        if (candidate / ".git").exists():
            return candidate
    raise FileNotFoundError(f"Could not locate git repo root from {__file__}")


DEFAULT_GRAPHS_DIR = _repo_root_from_file() / "graphs"


def read_graph(graph_name: BuiltinGraphName, graphs_dir: Path | None = None) -> nx.Graph:
    base_dir = graphs_dir if graphs_dir is not None else DEFAULT_GRAPHS_DIR
    return _read_graph_from_edges_csv(base_dir / graph_name / "edges.csv")


def read_geant_graph(graphs_dir: Path | None = None) -> nx.Graph:
    return read_graph("geant", graphs_dir=graphs_dir)


def read_nsfnet_graph(graphs_dir: Path | None = None) -> nx.Graph:
    return read_graph("nsfnet", graphs_dir=graphs_dir)


def read_secoqc_graph(graphs_dir: Path | None = None) -> nx.Graph:
    return read_graph("secoqc", graphs_dir=graphs_dir)


def synthetic_graph_snapshot(nodes: int, graphs_dir: Path | None = None) -> nx.Graph:
    if nodes < 1 or nodes > 99:
        raise ValueError("nodes must be between 1 and 99")
    if nodes % 3 != 0:
        print("Warning: synthetic graph snapshot may be malformed!", file=sys.stderr)

    base_dir = graphs_dir if graphs_dir is not None else DEFAULT_GRAPHS_DIR
    edge_list = pl.read_csv(base_dir / "generated" / "edges.csv")
    di_graph = nx.DiGraph(edge_list.select(["Source", "Target"]).rows())
    for edge in list(di_graph.edges()):
        if edge[0] > nodes:
            di_graph.remove_edge(edge[0], edge[1])
    isolated_nodes = list(nx.isolates(di_graph))
    di_graph.remove_nodes_from(isolated_nodes)
    return nx.Graph(di_graph)


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
