import polars as pl

# files = [f"out2/{GRAPH}_{walk}_hops.csv" for walk in ["r", "nb", "lrv"]]
# l = pl.read_csv(files[0])
# for r_file in files[1:]:
#     r = pl.read_csv(r_file)
#     l = l.join(r, on=["source", "target"], how="inner", validate="1:1")
#     assert l.shape[0] == r.shape[0]
# l.write_csv(f"data/{GRAPH}/hops.csv")
for graph in ["secoqc", "nsfnet", "geant"]:
    files = [f"out2/{graph}_{walk}_exposure.csv" for walk in ["r", "nb", "lrv"]]
    l = pl.read_csv(files[0])
    for r_file in files[1:]:
        r = pl.read_csv(r_file)
        l = l.join(r, on=["source", "target"], how="inner", validate="1:1")
        assert l.shape[0] == r.shape[0]
    l.write_csv(f"data/{graph}/exposure.csv")
for graph in ["secoqc", "nsfnet", "geant"]:
    l = pl.read_csv(f"data/{graph}/pairs.csv")
    r = pl.read_csv(f"data/{graph}/exposure.csv")
    r = r.select(["source", "target", "lrv_max_vis_prob","lrv_max_vis_node"])
    l = l.join(r, on=["source", "target"], how="inner", validate="1:1")
    assert l.shape[0] == r.shape[0]
    l.write_csv(f"data/{graph}/pairs.csv")