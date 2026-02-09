import polars as pl

GRAPH = "secoqc"
l = pl.read_csv(f"data/{GRAPH}/pairs.csv")
r = pl.read_csv(f"data/{GRAPH}/longest.csv")

KEYS = ["source", "target"]
m = l.join(r, on=KEYS, how="inner", validate="1:1")
m.write_csv(f"data/{GRAPH}/pairs.csv")