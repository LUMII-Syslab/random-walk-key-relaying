import polars as pl

GRAPH = "secoqc"
files = [f"{GRAPH}_{walk}_hops.csv" for walk in ["r", "nb", "lrv"]]
l = pl.read_csv(files[0])
for r in files[1:]:
    l = l.join(pl.read_csv(r), on=["source", "target"], how="inner", validate="1:1")
    assert l.shape[0] == r.shape[0]
l.write_csv(f"data/{GRAPH}/hops.csv")
