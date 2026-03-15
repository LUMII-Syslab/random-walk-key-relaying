from scipy.stats import binom
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pathlib import Path


def prob(g, N, chi):
    a = 1.0 - chi
    # P[X >= g] for X ~ Binomial(N, a)
    return binom.sf(g - 1, N, a)


def find_g(N, chi, threshold):
    for g in range(N, -1, -1):
        if prob(g, N, chi) >= threshold: return g
    return -1


def print_threshold_table(N_values, chi_values, threshold):
    data = {}
    for N in N_values:
        row = {}
        for chi in chi_values:
            g = find_g(N, chi, threshold)
            row[f"{chi:.2f}"] = g if g >= 0 else "-"
        data[N] = row

    df = pd.DataFrame(data).T
    df.index.name = "N"
    print(f"g such that P[X >= g] >= {threshold:.4f}")
    print(df.to_string())

    print("\nLaTeX table:")
    print(df.to_latex())


if __name__ == "__main__":
    N = 1024
    print(prob(20, N, 0.95))
    N_values = [32, 64, 128, 256, 512, 1024]
    chi_values = [0.95, 0.9, 0.85, 0.8, 0.75]
    threshold = 0.9999
    g_values = np.arange(0, N + 1)

    print_threshold_table(N_values, chi_values, threshold)

    plt.rcParams.update(
        {
            "axes.labelsize": 14,
            "xtick.labelsize": 12,
            "ytick.labelsize": 12,
            "legend.fontsize": 14,
            "axes.titlesize": 16,
        }
    )

    plt.figure(figsize=(6, 4))
    line_styles = ["-", "--", "-.", ":", (0, (3, 1, 1, 1))]
    colors = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple"]
    for i, chi in enumerate(chi_values):
        y = [prob(g, N, chi) for g in g_values]
        plt.plot(
            g_values,
            y,
            color=colors[i % len(colors)],
            linestyle=line_styles[i % len(line_styles)],
            linewidth=2.0,
            label=rf"$\chi={chi:.2f}$",
        )

    plt.xlabel(r'No. of good fragments ($g$) out of $N=1024$')
    plt.ylabel(r'Prob. of $\geq g$ good fragments')
    plt.title(r'Binomial tail probability for good fragments')

# 27 & 69 & 113 & 159 & 206
    plt.xticks([27, 69, 113, 159, 206])
    # plt.minorticks_on()
    plt.xlim(0, 256+128)
    plt.yticks([0, 0.5, 1.0])

    plt.grid(True, which="major", linestyle="--", alpha=0.45)
    plt.legend(loc="upper right")
    plt.tight_layout()
    plots_dir = Path("plots")
    plots_dir.mkdir(parents=True, exist_ok=True)
    output_path = plots_dir / "comb_N1024_tail_probability.pdf"
    plt.savefig(output_path, format="pdf", bbox_inches="tight")
    print(f"Saved plot to: {output_path}")
    plt.show()