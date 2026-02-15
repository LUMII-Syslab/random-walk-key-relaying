import polars as pl
import matplotlib.pyplot as plt
import translate
import numpy as np
import signal

signal.signal(signal.SIGINT, signal.SIG_DFL)

x = list(range(6, 100, 3))

def main():
    fig, (ax1, ax2) = plt.subplots(1,2, figsize=(11, 4))
    plot_throughput_avg(ax1)
    plot_hopcount_avg_and_median(ax2)
    plt.tight_layout()
    plt.show()

def avg_tput(x: int) -> dict[str, float]:
    res = dict()
    lrv_tput_csv = pl.read_csv(f"out/{x}/LRV/throughput.csv")
    res["lrv"] = lrv_tput_csv["lrv_throughput"].mean()
    nb_tput_csv = pl.read_csv(f"out/{x}/NB/throughput.csv")
    res["nb"] = nb_tput_csv["nb_throughput"].mean()
    r_tput_csv = pl.read_csv(f"out/{x}/R/throughput.csv")
    res["r"] = r_tput_csv["r_throughput"].mean()
    return res

def plot_throughput_avg(ax: plt.Axes):
    y_lrv = [avg_tput(x_i)["lrv"] for x_i in x]
    y_nb = [avg_tput(x_i)["nb"] for x_i in x]
    y_r = [avg_tput(x_i)["r"] for x_i in x]
    ax.plot(x, y_lrv, marker='^', markersize=4, linestyle='-', label="LRV")
    ax.plot(x, y_nb, marker='s', markersize=4, linestyle='--', label="NB")
    ax.plot(x, y_r, marker='o', markersize=4, linestyle=':', label="R")
    ax.legend(fontsize=12)
    ax.set_xlabel(translate.get_axis_label("node_count"),fontsize=12)
    ax.set_ylabel(translate.get_axis_label("avg_tput"),fontsize=12)
    ax.set_xticks(x, labels=[str(x_i) if i%6==0 else "" for i, x_i in enumerate(x)], fontsize=12)
    yticks = np.arange(0,2.5,0.5)
    ax.set_yticks(yticks, labels=[f"{y:.1f}" for y in yticks], fontsize=12)
    ax.yaxis.grid(True, alpha=0.5)

def avg_hopcount(x: int) -> dict[str, float]:
    res = dict()
    lrv_hop_csv = pl.read_csv(f"out/{x}/LRV/hops.csv")
    res["lrv"] = lrv_hop_csv["lrv_mean_hops"].mean()
    nb_hop_csv = pl.read_csv(f"out/{x}/NB/hops.csv")
    res["nb"] = nb_hop_csv["nb_mean_hops"].mean()
    r_hop_csv = pl.read_csv(f"out/{x}/R/hops.csv")
    res["r"] = r_hop_csv["r_mean_hops"].mean()
    return res

def median_hopcount(x: int) -> float:
    hop_csv = pl.read_csv(f"out/{x}/LRV/hops.csv")
    return hop_csv["lrv_q2_hops"].mean()

def plot_hopcount_avg_and_median(ax: plt.Axes):
    y_lrv = [avg_hopcount(x_i)["lrv"] for x_i in x]
    y_nb = [avg_hopcount(x_i)["nb"] for x_i in x]
    y_r = [avg_hopcount(x_i)["r"] for x_i in x]
    # y2 = [median_hopcount(x_i) for x_i in x]
    ax.plot(x, y_lrv, marker='^', markersize=4, linestyle='-', label="LRV")
    ax.plot(x, y_nb, marker='s', markersize=4, linestyle='--', label="NB")
    ax.plot(x, y_r, marker='o', markersize=4, linestyle=':', label="R")
    ax.legend(fontsize=12)
    ax.set_xlabel(translate.get_axis_label("node_count"),fontsize=12)
    ax.set_ylabel(translate.get_axis_label("avg_hops"),fontsize=12)

if __name__ == "__main__":
    main()