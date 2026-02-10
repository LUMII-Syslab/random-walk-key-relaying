import polars as pl

GRAPH = "secoqc"
walk = "r"
l = pl.read_csv(f"data/{GRAPH}/pairs.csv")
r = pl.read_csv(f"out2/{GRAPH}_{walk}_throughput.csv")

# r.rename({"throughput": "lrv_throughput"})
KEYS = ["source", "target"]
m = l.join(r, on=KEYS, how="inner", validate="1:1")
print(m.shape, r.shape)
assert m.shape[0] == r.shape[0]
m.write_csv(f"data/{GRAPH}/pairs.csv")
