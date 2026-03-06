import polars as pl

for graph in ["secoqc", "nsfnet", "geant"]:
    csv = pl.read_csv(f"data/{graph}/exposure.csv")
    # lrv_max_vis_prob,lrv_max_vis_node
    csv = csv.select(['source', 'target', 'lrv_max_vis_prob', 'lrv_max_vis_node'])
    # csv = csv.sort(['lrv_max_vis_prob'], descending=True)
    # csv.write_csv(f"data/{graph}/exposure.csv")
    csv = csv.filter(pl.col('lrv_max_vis_prob') > 0.0)
    csv = csv.filter(pl.col('lrv_max_vis_prob') < 1.0)
    csv = csv.sort(['lrv_max_vis_prob'], descending=True)
    csv = csv.head(3)
    print(csv.to_pandas().to_markdown())