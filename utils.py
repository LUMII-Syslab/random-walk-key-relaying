from dataclasses import dataclass
import polars as pl
from pathlib import Path
import networkx as nx
import sys

root_dir = Path(".").absolute()
data_dir = root_dir / "data"
graphs_dir = root_dir / "graphs"


# merges selected columns from rhs into lhs
def merge_csv(lhs: Path, rhs: Path, key: list[str], select: list[str]):
    l, r = pl.read_csv(lhs), pl.read_csv(rhs)
    r = r.select(key + select)
    out = l.join(r, on=key, how="inner", validate="1:1")
    out.write_csv(lhs)


def read_edge_list_csv(edges_csv: Path) -> nx.Graph:
    edges_df = pl.read_csv(edges_csv)
    edge_rows = edges_df.select(["Source", "Target"]).rows()
    return nx.Graph(edge_rows)



def synthetic_graph_snapshot(nodes: int) -> nx.Graph:
    if nodes < 1 or nodes > 99:
        raise ValueError("nodes must be between 1 and 99")
    if nodes % 3 != 0:
        print("Warning: synthetic graph snapshot may be malformed!", file=sys.stderr)
    edge_list = pl.read_csv(graphs_dir / "generated" / "edges.csv")
    di_graph = nx.DiGraph(edge_list.select(["Source", "Target"]).rows())
    for edge in list(di_graph.edges()):
        if edge[0] > nodes:
            di_graph.remove_edge(edge[0], edge[1])
    isolated_nodes = list(nx.isolates(di_graph))
    di_graph.remove_nodes_from(isolated_nodes)
    graph = nx.Graph(di_graph)
    return graph



# value may be cached because it is expensive to compute
def get_exposure(g: nx.Graph, src: str, tgt: str) -> float:
    # TODO: implement
    pass


# value may be cached because it is expensive to compute
def get_tput(g: nx.Graph, src: str, tgt: str) -> float:
    # TODO: implement
    pass


if __name__ == "__main__":
    g = synthetic_graph_snapshot(99)
    print(g)
