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

## Hardcoded graph adjacency lists

Named topologies are also hardcoded in the Python package `graphs/` (`NSFNET`,
`GEANT` in `graphs/__init__.py`). That lets callers pass a graph name alone —
useful for joblib cache keys, where hashing a short string is cheaper than
serializing a full adjacency list, and avoids rereading edge CSVs from disk on
every cache lookup. The synthetic generated graph (integer vertices, prefix
snapshots) lives in `graphs/generated/`.

## Node-disjoint paths (`suurballe.py`)

[`suurballe.py`](suurballe.py) implements Suurballe's algorithm for finding
`k` node-disjoint source–target paths of minimum total hop count in an
undirected, unweighted graph (Suurballe, *Networks* 4, 1974).

```py
from graphs import get_graph_int_adj_list
from suurballe import suurballe

adj = get_graph_int_adj_list("GEANT")
paths = suurballe(adj, s=0, t=1, k=2)
```

The input is a `dict[int, list[int]]` with contiguous keys `0 .. n-1`. Each
returned path is a list of node indices from `s` to `t`; internal vertices are
not shared across paths. Pass `k` equal to the local vertex connectivity
between `s` and `t` (e.g. from NetworkX) to obtain a maximum node-disjoint
path set.

Used by [`test_suurballe.py`](test_suurballe.py) for multipath (MP) protection analysis.
Integration tests against GÉANT are in [`test_suurballe.py`](test_suurballe.py):

```bash
pytest test_suurballe.py
```
