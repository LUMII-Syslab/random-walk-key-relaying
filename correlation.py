import polars as pl
import matplotlib.pyplot as plt

GRAPH = "geant"
data = pl.read_csv(f"data/{GRAPH}/pairs.csv")
data = data.select(["lrv_inflation", "lrv_nc_eff"])
data = data.filter(pl.col("lrv_nc_eff") >= 0)

plt.scatter(data["lrv_inflation"], data["lrv_nc_eff"])
plt.xlabel("Inflation")
plt.ylabel("Efficiency")
plt.title(f"Efficiency vs Inflation for {GRAPH}")
plt.show()