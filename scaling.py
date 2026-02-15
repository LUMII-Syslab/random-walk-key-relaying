import polars as pl
import matplotlib.pyplot as plt
import translate
import numpy as np
import signal
from pathlib import Path

signal.signal(signal.SIGINT, signal.SIG_DFL)

x = list(range(6, 100, 3))
walks = ["lrv", "nb", "r"]


def main():
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2,2, figsize=(11, 8))
    plot_throughput_avg(ax1)
    plot_hopcount_avg_and_median(ax2)
    plot_efficiency(ax3)
    plot_exposure(ax4)
    plt.tight_layout()
    save_plots_pdf()
    plt.tight_layout(pad=4)
    plt.show()

walk_styles = {
    "lrv": {
        "marker": "^",
        "linestyle": "-",
    },
    "nb": {
        "marker": "s",
        "linestyle": "-",
    },
    "r": {
        "marker": "o",
        "linestyle": "-",
    },
}

def avg_tput(x: int) -> dict[str, float]:
    res = dict()
    lrv_tput_csv = pl.read_csv(f"out/{x}/LRV/throughput.csv")
    res["lrv"] = lrv_tput_csv["lrv_throughput"].mean()
    nb_tput_csv = pl.read_csv(f"out/{x}/NB/throughput.csv")
    res["nb"] = nb_tput_csv["nb_throughput"].mean()
    r_tput_csv = pl.read_csv(f"out/{x}/R/throughput.csv")
    res["r"] = r_tput_csv["r_throughput"].mean()
    return res

def mean_metric(x: int, walk: str, file_name: str, col_name: str) -> float:
    csv = pl.read_csv(f"out/{x}/{walk.upper()}/{file_name}")
    return csv[col_name].mean()

def node_count_ticks(ax: plt.Axes):
    ax.set_xlabel(translate.get_axis_label("node_count"),fontsize=12)
    ax.set_xticks(x, labels=[str(x_i) if i%6==0 else "" for i, x_i in enumerate(x)], fontsize=12)

def plot_throughput_avg(ax: plt.Axes):
    for walk in walks:
        y = [mean_metric(x_i, walk, "throughput.csv", f"{walk}_throughput") for x_i in x]
        ax.plot(x, y, **walk_styles[walk], markersize=4, label=walk.upper())
    ax.legend(fontsize=12)
    node_count_ticks(ax)
    ax.set_ylabel(f"{translate.get_axis_label('tput')} avg", fontsize=12)
    yticks = np.arange(0,2.5,0.5)
    ax.set_yticks(yticks, labels=[f"{y:.1f}" for y in yticks], fontsize=12)
    ax.yaxis.grid(True, alpha=0.5)
    ax.set_title("Throughput vs network size", fontsize=14)
    ax.set_ylim(0,2.5)

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
    for walk in walks:
        y = [mean_metric(x_i, walk, "hops.csv", f"{walk}_mean_hops") for x_i in x]
        ax.plot(x, y, **walk_styles[walk], markersize=4, label=walk.upper())
    ax.legend(fontsize=12)
    node_count_ticks(ax)
    ax.set_ylabel(f"{translate.get_axis_label('hops')} avg",fontsize=12)
    ax.yaxis.grid(True, alpha=0.5)
    ax.set_title("Hop count vs network size", fontsize=14)
    ax.set_ylim(0,100)
    ax.tick_params(axis="y", labelsize=12)

def nc_efficiency(tput: float, exposure: float, conn: int) -> float:
    return tput * (1 - exposure) / (conn - 1)

def join_col(lhs: pl.DataFrame, rhs: pl.DataFrame, col: str) -> pl.DataFrame:
    return lhs.join(rhs.select(["source","target",col]), on=["source","target"], how="inner", validate="1:1")

def avg_efficiency(x: int) -> dict[str, float]:
    res = dict()
    for walk in walks:
        tput_csv = pl.read_csv(f"out/{x}/{walk.upper()}/throughput.csv")
        conn_csv = pl.read_csv(f"out/{x}/{walk.upper()}/connectivity.csv")
        exp_csv = pl.read_csv(f"out/{x}/{walk.upper()}/exposure.csv")
        params = tput_csv.select(["source","target"])
        params = join_col(params, tput_csv, f"{walk}_throughput")
        params = join_col(params, exp_csv, f"{walk}_max_vis_prob")
        params = join_col(params, conn_csv, "connectivity")
        params = params.drop(["source","target"])
        nc_eff = [nc_efficiency(*row) for row in params.rows()]
        res[walk] = np.mean(nc_eff)
    return res

def plot_efficiency(ax: plt.Axes):
    for walk in walks:
        y = [avg_efficiency(x_i)[walk] for x_i in x]
        ax.plot(x,y, **walk_styles[walk], markersize=4, label=walk.upper())
    ax.legend(fontsize=12)
    node_count_ticks(ax)
    ax.set_ylabel(f"{translate.get_axis_label('nc_eff')} avg",fontsize=12)
    ax.yaxis.grid(True, alpha=0.5)
    ax.set_title(f"T-put efficiency vs network size",fontsize=14)
    ax.set_ylim(0,1)
    ax.tick_params(axis="y", labelsize=12)

def plot_exposure(ax: plt.Axes):
    for walk in walks:
        y = [mean_metric(x_i, walk, "exposure.csv", f"{walk}_max_vis_prob") for x_i in x]
        ax.plot(x, y, **walk_styles[walk], markersize=4, label=walk.upper())
    ax.legend(fontsize=12)
    node_count_ticks(ax)
    ax.set_ylabel(translate.get_axis_label("avg_max_vis_prob"), fontsize=12)
    ax.yaxis.grid(True, alpha=0.5)
    ax.set_title("Max visit probability vs network size", fontsize=14)
    ax.set_ylim(0.5,1)
    ax.tick_params(axis="y", labelsize=12)

def save_plots_pdf():
    plots_dir = Path("plots")
    plots_dir.mkdir(parents=True, exist_ok=True)
    plot_specs = [
        ("throughput.pdf", plot_throughput_avg),
        ("hopcount.pdf", plot_hopcount_avg_and_median),
        ("efficiency.pdf", plot_efficiency),
        ("exposure.pdf", plot_exposure),
    ]
    for file_name, plot_fn in plot_specs:
        fig, ax = plt.subplots(figsize=(6, 4))
        plot_fn(ax)
        fig.tight_layout()
        fig.savefig(plots_dir / file_name, format="pdf")
        plt.close(fig)

if __name__ == "__main__":
    main()