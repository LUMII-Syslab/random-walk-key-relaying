import polars as pl
from translate import translations
graph = "geant"
csv = pl.read_csv(f"data/{graph}/pairs.csv")
csv = csv.filter(pl.col("lrv_nc_eff") >= 0)
# print(csv.shape[0])
csv = csv.filter(pl.col("lrv_nc_eff") > 0.99)
csv = csv.drop(["lrv_mf_eff", "lrv_inflation","max_flow","longest"])
csv = csv.rename(translations)
csv = csv.sort(["$d$"],descending=True)
latex = csv.to_pandas().style.format(precision=2).to_latex()
# latex = latex.replace("_", "\\_")
new_latex = []
counter = 0
for line in latex.split("\n"):
    if "&" in line:
        if counter == 0:
            new_latex.append(line)
        else:
            new_latex.append(f"{counter} & " + " & ".join(line.split(" & ")[1:]))
        counter += 1
    else:
        new_latex.append(line)
latex = "\n".join(new_latex)
print(latex)