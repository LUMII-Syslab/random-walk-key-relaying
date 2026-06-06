# Random Walk Key Relaying

Simulates and analyzes random walk key relaying in context of QKD networks.

## Network topologies

Node and edge CSV files are stored in the `graphs/` directory.

| Graph   | Nodes | Edges | Avg Degree | Description |
|---------|-------|-------|------------|-------------|
| SECOQC  | 6     | 8     | 2.67       | Vienna metro-scale QKD testbed (2004-2008) |
| NSFNET  | 14    | 21    | 3.00       | US academic backbone topology (1991) |
| GÉANT   | 43    | 59    | 2.74       | Pan-European research network (links >1000km pruned) |

Distances are calculated for pairs of nodes using the Haversine formula based on latitude and longitude from the nodes CSV.

```py
R_KM = 6371.0088  # mean Earth radius in km

def haversine_km(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R_KM * math.atan2(math.sqrt(a), math.sqrt(1 - a))
```

## Python prerequisites

Ubuntu + `pyenv` + `pyenv-virtualenv` setup:

Pyenv version manager installation

```bash
sudo apt update
sudo apt install -y make build-essential libssl-dev zlib1g-dev libbz2-dev libreadline-dev libsqlite3-dev curl git libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev libffi-dev liblzma-dev

curl -fsSL https://pyenv.run | bash

echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo '[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo 'eval "$(pyenv init - bash)"' >> ~/.bashrc
echo 'eval "$(pyenv virtualenv-init -)"' >> ~/.bashrc
exec "$SHELL"
```

Create and enable a new 3.12 venv

```bash
pyenv install 3.12.11
pyenv virtualenv 3.12.11 random-walk-key-relaying
pyenv local random-walk-key-relaying
pyenv activate random-walk-key-relaying
```

Python package requirement installation

```bash

python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Retrieving graph adjacency lists

Named topologies are also hardcoded in the Python package `graphs/` (`NSFNET`, `GEANT` in `graphs/__init__.py`) and in `cpp/graphs.hpp` for the C++ binaries (`nsfnet`, `geant`).
That lets callers pass a graph name alone, which is useful for joblib cache keys, where hashing a short string is cheaper than serializing a full adjacency list, and avoids rereading edge CSVs from disk on every cache lookup.
The synthetic generated graph (integer vertices, prefix snapshots) lives in `graphs/generated/`.

## Node-disjoint paths (`suurballe.py`)

[`suurballe.py`](suurballe.py) implements Suurballe's algorithm for finding `k` node-disjoint source-target paths of minimum total hop count in an undirected, unweighted graph (Suurballe, *Networks* 4, 1974).

```py
from graphs import get_graph_int_adj_list
from suurballe import suurballe

adj = get_graph_int_adj_list("GEANT")
paths = suurballe(adj, s=0, t=1, k=2)
```

The input is a `dict[int, list[int]]` with contiguous keys `0 .. n-1`.
Each returned path is a list of node indices from `s` to `t`; internal vertices are not shared across paths.
Pass `k` equal to the local vertex connectivity between `s` and `t` (e.g. from NetworkX) to obtain a maximum node-disjoint path set.

Used by [`test_suurballe.py`](test_suurballe.py) for multipath (MP) protection analysis.
Integration tests against GÉANT are in [`test_suurballe.py`](test_suurballe.py):

```bash
pytest test_suurballe.py
```

## C++ tools

Build from `cpp/` (`make` uses `-O2` by default; `DEBUG=1 make` for debug symbols):

```bash
cd cpp
make
```

Walk simulators take `-g` / `--graph`: a built-in name (`nsfnet`, `geant`) or a path to an edges CSV.
Default graph is `geant`.
Run commands below assume the current working directory is `cpp/`.

## Random walk hop statistics (`cpp/build/hops`)

Monte Carlo distribution of hop counts for random walks from `s` to `t`.
Runs are parallelized across CPU cores.
Default graph is GÉANT, walk variant HS, 1000 samples.

```bash
./build/hops -s PRA -t VIE -n 10000

./build/hops -s SEA -t ATL -g nsfnet -n 10000 --erase-loops
```

| Flag | Meaning |
|------|---------|
| `-s`, `--src-node` | Source node name (required) |
| `-t`, `--tgt-node` | Target node name (required) |
| `-g`, `--graph` | `nsfnet`, `geant`, or path to edges CSV (default `geant`) |
| `-n`, `--no-of-runs` | Monte Carlo samples (default 1000) |
| `-w`, `--rw-variant` | Walk variant: `R`, `NB`, `LRV`, `NC`, `HS` (default `HS`) |
| `--erase-loops` | Count hops on the loop-erased path instead of the raw walk |
| `--record-paths` | Print each sampled path after the summary |

Reports min, percentiles (p25 through p99), max, mean, standard deviation, and a 95% CI for the mean.

Example output:

```
context: -s=PAR -t=MIL -g=geant -w=HS --no-of-runs=1000 --record-paths=false --erase-loops=false
min: 2
p25: 4
median / p50: 8
p75: 16
p90: 26
p95: 31
p99: 44
max: 69
mean: 11.1
sd: 9.9
95% CI for mean: [10.5, 11.7]
```

## Random Flow Cartel exposure (`cpp/build/exposure`)

Estimates random flow cartel exposure for a fixed source-target pair: the probability that a loop-erased random walk from `s` to `t` visits at least one node in a cartel.
For cartel sizes 2 and 3, exposure uses inclusion-exclusion on single/pair/triple visit counts accumulated over many walk samples (HS + loop erasure by default).

```bash
./build/exposure -s SEA -t ATL -g nsfnet -m 2 -n 10000

./build/exposure -s PRA -t VIE -m 2 -n 10000
```

The second command uses the default GÉANT graph.

| Flag | Meaning |
|------|---------|
| `-s`, `--src-node` | Source node name (required for simulation) |
| `-t`, `--tgt-node` | Target node name (required for simulation) |
| `-g`, `--graph` | `nsfnet`, `geant`, or path to edges CSV (default `geant`) |
| `-m`, `--cartel-size` | Cartel size (1, 2, or 3) |
| `-n`, `--no-of-runs` | Monte Carlo samples (default 10000) |
| `-w`, `--rw-variant` | Walk variant: `R`, `NB`, `LRV`, `NC`, `HS` (default `HS`) |

The tool enumerates every cartel of size `m` and reports:

- `mean_exposure_all`: average exposure over all cartels
- `mean_exposure_eligible`: average over eligible cartels only; neither `s` nor `t` is in the cartel, and `s`-`t` stays connected after removing cartel nodes
- `max_exposure_eligible` / `max_exposure_eligible_cartel`: worst eligible cartel and its nodes
- `total_cartels`, `eligible_cartels`: counts for context

Example output:

```
context: -s=SEA -t=ATL -g=nsfnet -w=HS -n=10000 -m=2
mean_exposure_all: 0.666214
mean_exposure_eligible: 0.532700
max_exposure_eligible: 0.893000
max_exposure_eligible_cartel: CMI HOU
total_cartels: 91
eligible_cartels: 65
```
