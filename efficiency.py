import polars as pl

for graph in ["secoqc", "nsfnet", "geant"]:
    pairs_csv = pl.read_csv(f"data/{graph}/pairs.csv")
    rows = pairs_csv.select(["lrv_tput", "max_flow", "node_conn", "lrv_max_vis_prob"]).rows()
    mf_efficiency = [round(row[0] / row[1], 2) for row in rows]
    # efficiency = t*(1-x) / (c-1)
    # nc_efficiency = [round(t*(1-x) / (c-1), 2) if c<=1 else -1 for (t,_,c,x) in rows]
    nc_efficiency = []
    for (t,_,c,x) in rows:
        if c<=1: nc_efficiency.append(-1.0)
        else: nc_efficiency.append(round(t*(1-x) / (c-1), 2))
    
    inflation = []
    rows2 = pairs_csv.select(["lrv_hops", "shortest"]).rows()
    inflation = [round(row[0] / row[1], 2) for row in rows2]

    inflation_plus = []
    rows3 = pairs_csv.select(["lrv_q2_hops", "shortest"]).rows()
    inflation_plus = [round(row[0] / row[1], 2) for row in rows3]

    pairs_csv = pairs_csv.with_columns(pl.Series("lrv_mf_eff", mf_efficiency))
    pairs_csv = pairs_csv.with_columns(pl.Series("lrv_nc_eff", nc_efficiency))
    pairs_csv = pairs_csv.with_columns(pl.Series("lrv_inflation", inflation))
    pairs_csv = pairs_csv.with_columns(pl.Series("lrv_infl_plus", inflation_plus))
    pairs_csv.write_csv(f"data/{graph}/pairs.csv")