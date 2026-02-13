import polars as pl
import matplotlib.pyplot as plt
import signal
from translate import translations, expansions
# import numpy as np
# from scipy.optimize import curve_fit
signal.signal(signal.SIGINT, signal.SIG_DFL)

GRAPH = "geant"
data = pl.read_csv(f"data/{GRAPH}/pairs.csv")

columns = ["lrv_q2_hops", "lrv_nc_eff"]
data = data.select(columns)
data = data.filter(pl.col("lrv_nc_eff") >= 0)

correlation = data.select(pl.corr(data[columns[0]], data[columns[1]]))
print(correlation)
plt.rcParams.update({'font.size': 14})
x = data[columns[0]].to_numpy()
y = data[columns[1]].to_numpy()
plt.scatter(x, y)

# def invpow(x, a, b, c, p): # inverse-power model: y = c + a / (x + b)^p
#     # ignore c and b
#     c = 0
#     return c + a / np.power(x + b, p)

# params, _ = curve_fit(invpow, x, y, maxfev=200000)
# a,b,c,p = params

# y_hat = invpow(x, a, b, c, p)
# ss_res = np.sum((y - y_hat) ** 2)
# ss_tot = np.sum((y - y.mean()) ** 2)
# r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")

# x_line = np.linspace(x.min(), x.max(), 400)
# y_line = invpow(x_line, a, b, c, p)
# print(f"model: y = {c:.6f} + {a:.6f}/(x+{b:.6f})^{p:.6f}    R2 = {r2:.4f}")
# plt.plot(x_line, y_line, linewidth=2, label=f"inv-power fit (R²={r2:.2f})", color="red")
# plt.legend()

title_parts = []
label_parts = []
for i in range(len(columns)):
    if columns[i] in translations:
        label_parts.append(f"{translations[columns[i]]} ({expansions[columns[i]]})")
        title_parts.append(translations[columns[i]])
plt.xlabel(label_parts[0])
plt.ylabel(label_parts[1])
plt.title(f"{' vs '.join(title_parts)} ($\\rho$ = {round(correlation.item(), 2)}, {GRAPH}, LRV)")
plt.tight_layout()
plt.savefig(f"plots/{GRAPH}_correlation.pdf")
plt.show()