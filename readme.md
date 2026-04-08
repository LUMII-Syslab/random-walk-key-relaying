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
