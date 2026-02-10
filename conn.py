import networkx as nx
import polars as pl

graphs = ["secoqc", "nsfnet", "geant"]
for graph in graphs:
    edges_csv = f"graphs/{graph}/edges.csv"
    edges_pl = pl.read_csv(edges_csv).select(["Source", "Target"])
    edge_list = [(row["Source"], row["Target"]) for row in edges_pl.to_dicts()]
    nodes = set(edges_pl["Source"]).union(set(edges_pl["Target"]))
    conn = pl.DataFrame({"source": pl.Series([], dtype=pl.Utf8), "target": pl.Series([], dtype=pl.Utf8), "node_conn": pl.Series([], dtype=pl.Int64)})
    G = nx.Graph(edge_list)
    for s in nodes:
        for t in nodes:
            if s >= t: continue
            k = nx.node_connectivity(G, s, t)
            row = pl.DataFrame({"source": [s], "target": [t], "node_conn": [k]})
            print(row)
            print(conn)
            conn = conn.vstack(row)
    l = pl.read_csv(f"data/{graph}/pairs.csv")
    l = l.join(conn, on=["source", "target"], how="inner", validate="1:1")
    assert l.shape[0] == conn.shape[0]
    l.write_csv(f"data/{graph}/pairs.csv")

