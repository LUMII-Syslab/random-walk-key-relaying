import polars as pl

for graph in ["secoqc", "nsfnet", "geant"]:
    pairs_csv = pl.read_csv(f"data/{graph}/pairs.csv")
    rows = pairs_csv.select(["lrv_tput", "max_flow", "node_conn", ]).rows()
    mf_efficiency = [round(row[0] / row[1], 2) for row in rows]
    nc_efficiency = [round(row[0] / row[2], 2) for (t,_,c) in rows]

    pairs_csv = pairs_csv.with_columns(pl.Series("lrv_mf_eff", mf_efficiency))
    pairs_csv = pairs_csv.with_columns(pl.Series("lrv_nc_eff", nc_efficiency))
    pairs_csv.write_csv(f"data/{graph}/pairs.csv")