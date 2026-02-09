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

## `Data` directory

This data is light and can be stored in a Git version controlled directory.

Currently `pairs.csv` contain the following columns:
- `source`, `target`: node IDs
- `shortest`: shortest path length
- `max_flow`: max # of edge-disjoint paths

We should add (TODO) the following info:
1. expected number of hops per each random walk variant
2. mean throughput over a simulation of 1000s duration
3. longest possible path length?

We approximate the longest path by a heuristic search bound by 0.1s per pair.

## Throughput simulation

Default configuration that was used to get data.

```json
{
    "key_size": 256,
    "node_buff_keys": 100000,
    "link_buff_bits": 100000,
    "links_empty_at_start": true,
    "qkd_skr": 1000,
    "latency": 0.05,
    "sim_duration": 1000.0,
    "random_seed": 2026
}
```

## Usage

```bash
# Run all phases (simulation -> derivation -> visualization)
python3 throughput.py

# Run individual phases
pypy3 throughput.py --mode sim      # Simulation (PyPy-compatible) -> raw/
python3 throughput.py --mode info   # Derive info from raw data -> info/
python3 throughput.py --mode charts # Generate visualizations -> charts/

# Quick test run (shorter simulations, lower DPI)
python3 throughput.py --quick

# Control parallelism
python3 throughput.py --workers 4      # Use 4 workers
python3 throughput.py --no-parallel    # Sequential (for debugging)
```

## Output Structure

```
out/<graph>/<variant>/
├── raw/                    # Phase 1: Simulation (JSON)
│   ├── config.json         # Simulation parameters
│   ├── simulation_result.json
│   ├── pairwise_results.json
│   └── hop_results.json
├── info/                   # Phase 2: Derivation (JSON, CSV, TXT)
│   ├── throughput.json
│   ├── throughput.txt
│   ├── pairwise.json
│   ├── pairwise.csv
│   ├── pairwise.txt
│   ├── hitting.json
│   ├── hitting.txt
│   ├── hops.json
│   ├── hops.csv
│   ├── hops.txt
│   ├── visits.json
│   └── visits.txt
└── charts/                 # Phase 3: Visualization (PNG)
    ├── throughput.png
    ├── throughput_time_series.png
    ├── throughput_freq_distribution.png
    ├── throughput_heatmap.png
    ├── hopcount_heatmap.png
    ├── hitting_heatmap.png
    ├── hop_counts.png
    ├── edge_multiplicity.png
    └── node_hitting.png
```

- `--quick` outputs to `quick/` instead of `out/`
- Variants: `r` (random), `nb` (non-backtracking), `lrv` (least-recently-visited)

## Graph Topologies

## Other Tools

**Add edge weights from node coordinates:**
```bash
python3 distances.py nodes.csv edges.csv edges_weighted.csv
```
