import polars as pl

GRAPH = "secoqc"
# files = [f"out2/{GRAPH}_{walk}_hops.csv" for walk in ["r", "nb", "lrv"]]
# l = pl.read_csv(files[0])
# for r_file in files[1:]:
#     r = pl.read_csv(r_file)
#     l = l.join(r, on=["source", "target"], how="inner", validate="1:1")
#     assert l.shape[0] == r.shape[0]
# l.write_csv(f"data/{GRAPH}/hops.csv")
l = pl.read_csv(f"data/{GRAPH}/pairs.csv")
r = pl.read_csv(f"data/{GRAPH}/hops.csv")
r = r.select(["source", "target", "lrv_mean_hops"])
r = r.rename({"lrv_mean_hops": "lrv_hops"})
l = l.join(r, on=["source", "target"], how="inner", validate="1:1")
assert l.shape[0] == r.shape[0]
l.write_csv(f"data/{GRAPH}/pairs.csv")