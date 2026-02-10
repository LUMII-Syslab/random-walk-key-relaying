import polars as pl

GRAPH = "secoqc"
df = pl.read_csv(f"data/{GRAPH}/pairs.csv")
df_copy = df.clone()
df = df.drop(["lrv_tput_rev","nb_throughput","nb_tput_rev","r_throughput","r_tput_rev"])
df = df.rename({"lrv_throughput": "lrv_tput"})
df.write_csv(f"data/{GRAPH}/pairs.csv")
df_copy = df_copy.drop(["shortest", "max_flow", "longest"])
df_copy.write_csv(f"data/{GRAPH}/tputs.csv")