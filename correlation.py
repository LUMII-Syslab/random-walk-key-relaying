import polars as pl
import matplotlib.pyplot as plt

GRAPH = "geant"
data = pl.read_csv(f"data/{GRAPH}/pairs.csv")
data = data.select(["lrv_hops", "lrv_efficiency"])

plt.scatter(data["lrv_hops"], data["lrv_efficiency"])
plt.xlabel("Hop Count")
plt.ylabel("Efficiency")
plt.title(f"Efficiency vs Hop Count for {GRAPH}")
plt.show()