# Random Walk Key Relaying Simulation

Simulates and analyzes random walk key relaying throughput in QKD networks.

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
