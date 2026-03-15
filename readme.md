# Random Walk Key Relaying

Simulates and analyzes random walk key relaying in context of QKD networks.

## Network topologies

Node and edge CSV files are stored in the `graphs/` directory.

| Graph   | Nodes | Edges | Avg Degree | Description |
|---------|-------|-------|------------|-------------|
| SECOQC  | 6     | 8     | 2.67       | Vienna metro-scale QKD testbed (2004–2008) |
| NSFNET  | 14    | 21    | 3.00       | US academic backbone topology (1991) |
| GÉANT   | 43    | 59    | 2.74       | Pan-European research network (links >1000km pruned) |

Distances are calculated for pairs of nodes using the Haversine formula
based on latitude and longitude from the nodes CSV.

```py
R_KM = 6371.0088  # mean Earth radius in km

def haversine_km(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R_KM * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

## Setup

Ubuntu + `pyenv` + `pyenv-virtualenv`:

```bash
sudo apt update
sudo apt install -y make build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev curl git libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev

curl -fsSL https://pyenv.run | bash

echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo '[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo 'eval "$(pyenv init - bash)"' >> ~/.bashrc
echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc
exec "$SHELL"

pyenv install 3.12.8
pyenv virtualenv 3.12.8 random-walk-key-relaying
pyenv local random-walk-key-relaying
pyenv activate random-walk-key-relaying

python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Plotting guidelines

1. Start with figure size
2. Override Matplotlib font sizes before plotting
3. Do not rely on color alone for multi-series plots
4. Use thicker lines for plotted series
5. Always set `xlabel`, `ylabel`, and `title`.
6. Prefer explicit `xticks`, `yticks`, and axis limits
7. Add a major grid, place the legend explicitly
8. call `plt.tight_layout()` before saving
8. Save final figures into `plots/` as PDF files

```py
from pathlib import Path

plt.figure(figsize=(6, 4))

plt.rcParams.update(
    {
        "axes.labelsize": 14,
        "xtick.labelsize": 12, with
   `bbox_inches="tight"`.
        "ytick.labelsize": 12,
        "legend.fontsize": 14,
        "axes.titlesize": 16,
    }
)

colors = ["tab:blue", "tab:orange", "tab:green", "tab:red", "tab:purple"]
line_styles = ["-", "--", "-.", ":", (0, (3, 1, 1, 1))]

for i, series in enumerate(series_list):
    plt.plot(
        x_values,
        series.y_values,
        color=colors[i % len(colors)],
        linestyle=line_styles[i % len(line_styles)],
        linewidth=2.0,
        label=series.label,
    )

plt.xlabel("...")
plt.ylabel("...")
plt.title("...")
plt.xticks([...])
plt.yticks([...])
plt.grid(True, which="major", linestyle="--", alpha=0.45)
plt.legend(loc="upper right")
plt.tight_layout()

plots_dir = Path("plots")
plots_dir.mkdir(parents=True, exist_ok=True)
plt.savefig(plots_dir / "figure.pdf", format="pdf", bbox_inches="tight")
```