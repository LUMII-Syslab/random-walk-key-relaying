import polars as pl

GRAPH = "secoqc"
l = pl.read_csv(f"data/{GRAPH}/pairs.csv")
r = pl.read_csv(f"out2/throughput.csv")

# r.rename({"throughput": "lrv_throughput"})
KEYS = ["source", "target"]
m = r.join(l, on=KEYS, how="inner", validate="1:1")
print(m.shape, l.shape)
assert m.shape[0] == l.shape[0]
m.write_csv(f"data/{GRAPH}/pairs.csv")
