"""
Measures transmission throughput of random walk key relaying in a QKD network.

Usage:
    python throughput.py --mode sim       # Run simulations only (PyPy-compatible) -> raw/
    python throughput.py --mode info      # Derive info from raw data -> info/
    python throughput.py --mode charts    # Generate visualizations -> charts/
    python throughput.py --mode all       # Run all phases (default)

Notes / fixes:
- Throughput over a window is a scaled COUNT of arrivals in that window.
  If arrivals were Poisson, counts ~ Poisson, throughput is scaled Poisson (discrete, skewed if mean small).
- Sliding-window samples are strongly autocorrelated; histogram of those samples is not an i.i.d. distribution sample.
- We therefore compute both:
    (1) sliding-window throughput time series (for dynamics)
    (2) non-overlapping-window throughput samples (for distribution/statistics)
"""

import argparse
import json
import os
import signal

signal.signal(signal.SIGINT, signal.SIG_DFL)

# Import simulation module (pure Python, PyPy-compatible)
from simulate import (
    SimConfig,
    RelayNetwork,
    SimulationResult,
    run_simulation,
    run_pairwise_simulations,
    run_hop_analysis,
    HEATMAP_NODES,
    HOP_ANALYSIS_SOURCES,
    GRAPH_PAIRS,
)

# Runtime settings (set by --quick flag)
QUICK_MODE = False
OUTPUT_BASE = "out"
DPI = 150
HEATMAP_SIM_DURATION = 100.0
HOP_SIM_DURATION = 100.0

# VISUALIZATION AND ANALYSIS PARAMETERS
TICK_INTERVAL = 1  # seconds between throughput measurements (sliding window)
WINDOW_SIZE = 10.0  # seconds for sliding window throughput
HIST_BIN_WIDTH = 100.0  # bits/s bins for histogram (non-overlapping samples)
MIN_KEYS_IN_WINDOW = 1  # min keys in window before recording sliding throughput
BURN_IN = 0 * WINDOW_SIZE  # ignore early transient in stats


def run_all_simulations(args, graphs, variants, output_base: str, sim_duration: float):
    """Run all simulations and save results to JSON files."""
    import random
    random.seed(2026)
    
    for name, nodes_csv, edges_csv in graphs:
        if name not in GRAPH_PAIRS:
            print(f"{name}: missing S/T pair")
            continue
        S, T = GRAPH_PAIRS[name]
        
        output_dir = os.path.join(output_base, name)
        os.makedirs(output_dir, exist_ok=True)
        
        config = SimConfig(sim_duration=sim_duration)
        graph = RelayNetwork(nodes_csv, edges_csv, config=config)
        
        if S not in graph.nodes or T not in graph.nodes:
            print(f"{name}: S/T not in node list ({S}, {T})")
            continue
        
        print(f"\n{'='*60}")
        print(f"{name}: S={S}, T={T}")
        print(f"{'='*60}")
        
        # Main throughput simulations for all variants
        for variant in variants:
            print(f"\n[{name}/{variant}] Running main throughput simulation...")
            result, config = run_simulation(graph, S, T, variant, name)
            
            variant_prefix = {"random": "r", "nonbacktracking": "nb", "lrv": "lrv"}[variant]
            raw_dir = os.path.join(output_dir, variant_prefix, "raw")
            os.makedirs(raw_dir, exist_ok=True)
            
            # Save config
            config_path = os.path.join(raw_dir, "config.json")
            with open(config_path, "w") as f:
                json.dump(config, f, indent=2)
            
            # Save simulation result (raw data only)
            result_path = os.path.join(raw_dir, "simulation_result.json")
            result.save(result_path)
            print(f"  -> Saved {len(result.arrival_times)} arrivals to {result_path}")
        
        # Pairwise metrics (for geant and nsfnet only) - all variants
        if name in HEATMAP_NODES:
            heatmap_duration = HEATMAP_SIM_DURATION if not args.quick else 10.0
            
            for heatmap_variant in variants:
                variant_prefix = {"random": "r", "nonbacktracking": "nb", "lrv": "lrv"}[heatmap_variant]
                print(f"\n[{name}/{variant_prefix}] Running pairwise simulations...")
                config_heatmap = SimConfig(sim_duration=heatmap_duration)
                graph_heatmap = RelayNetwork(nodes_csv, edges_csv, config=config_heatmap)
                
                pairwise_results = run_pairwise_simulations(
                    graph_heatmap,
                    selected_nodes=HEATMAP_NODES[name],
                    variant=heatmap_variant,
                    sim_duration=heatmap_duration,
                    graph_name=name,
                    parallel=not args.no_parallel,
                    num_workers=args.workers,
                )
                
                raw_dir = os.path.join(output_dir, variant_prefix, "raw")
                os.makedirs(raw_dir, exist_ok=True)
                
                pairwise_path = os.path.join(raw_dir, "pairwise_results.json")
                with open(pairwise_path, "w") as f:
                    json.dump(pairwise_results, f, indent=2)
                print(f"  -> Saved pairwise results to {pairwise_path}")
        
        # Hop count analysis (all variants)
        if name in HOP_ANALYSIS_SOURCES:
            hop_source = HOP_ANALYSIS_SOURCES[name]
            hop_duration = HOP_SIM_DURATION if not args.quick else 10.0
            
            for hop_variant in variants:
                print(f"\n[{name}/{hop_variant}] Running hop analysis from {hop_source}...")
                config_hop = SimConfig(sim_duration=hop_duration)
                graph_hop = RelayNetwork(nodes_csv, edges_csv, config=config_hop)
                
                hop_results = run_hop_analysis(
                    graph_hop,
                    source=hop_source,
                    variant=hop_variant,
                    sim_duration=hop_duration,
                    parallel=not args.no_parallel,
                    num_workers=args.workers,
                )
                
                variant_prefix = {"random": "r", "nonbacktracking": "nb", "lrv": "lrv"}[hop_variant]
                raw_dir = os.path.join(output_dir, variant_prefix, "raw")
                os.makedirs(raw_dir, exist_ok=True)
                
                hop_path = os.path.join(raw_dir, "hop_results.json")
                with open(hop_path, "w") as f:
                    json.dump({"source": hop_source, "results": hop_results}, f, indent=2)
                print(f"  -> Saved hop results to {hop_path}")
    
    print(f"\n{'='*60}")
    print("All simulations complete!")
    print(f"{'='*60}")


def run_derivations(graphs, variants, output_base: str):
    """Derive info from raw simulation results. Reads from raw/, writes to info/."""
    import analysis
    import csv
    
    for name, nodes_csv, edges_csv in graphs:
        if name not in GRAPH_PAIRS:
            continue
        S, T = GRAPH_PAIRS[name]
        
        output_dir = os.path.join(output_base, name)
        
        print(f"\n{'='*60}")
        print(f"{name}: Deriving info from raw data")
        print(f"{'='*60}")
        
        for variant in variants:
            variant_prefix = {"random": "r", "nonbacktracking": "nb", "lrv": "lrv"}[variant]
            variant_dir = os.path.join(output_dir, variant_prefix)
            raw_dir = os.path.join(variant_dir, "raw")
            info_dir = os.path.join(variant_dir, "info")
            os.makedirs(info_dir, exist_ok=True)
            
            # Load config
            config_path = os.path.join(raw_dir, "config.json")
            if not os.path.exists(config_path):
                print(f"  [{variant}] No config found at {config_path}")
                continue
            
            with open(config_path, "r") as f:
                raw_config = json.load(f)
            
            # === Throughput analysis ===
            result_path = os.path.join(raw_dir, "simulation_result.json")
            if os.path.exists(result_path):
                print(f"\n[{name}/{variant}] Deriving throughput info...")
                result = SimulationResult.load(result_path)
                
                analysis_config = {
                    "KEY_SIZE": raw_config["key_size"],
                    "NODE_BUFF_KEYS": raw_config["node_buff_keys"],
                    "LINK_BUFF_BITS": raw_config["link_buff_bits"],
                    "LINKS_EMPTY_AT_START": raw_config["links_empty_at_start"],
                    "QKD_SKR": raw_config["qkd_skr"],
                    "LATENCY": raw_config["latency"],
                    "TICK_INTERVAL": TICK_INTERVAL,
                    "WINDOW_SIZE": WINDOW_SIZE,
                    "SIM_DURATION": raw_config["sim_duration"],
                    "HIST_BIN_WIDTH": HIST_BIN_WIDTH,
                    "MIN_KEYS_IN_WINDOW": MIN_KEYS_IN_WINDOW,
                    "BURN_IN": BURN_IN,
                    "S": S,
                    "T": T,
                    "VARIANT": {"random": "R", "nonbacktracking": "NB", "lrv": "LRV"}[variant],
                    "VARIANT_LONG": variant,
                    "GRAPH": name,
                    "nodes_count": raw_config.get("nodes_count", 0),
                    "edges_count": raw_config.get("edges_count", 0),
                }
                
                arrival_times = result.arrival_times
                analyzer = analysis.Analyzer(analysis_config)
                summary = analyzer.compute_summary(arrival_times)
                arrival = analyzer.compute_arrival_metrics(arrival_times, summary)
                non_overlapping = analyzer.compute_non_overlapping_throughput(arrival_times)
                sliding = analyzer.compute_sliding_window_metrics(arrival_times)
                log_domain = analyzer.compute_log_domain_metrics(non_overlapping.thr_bins)
                
                # Save throughput.txt (human-readable)
                analyzer.print_summary(
                    summary, arrival, non_overlapping, sliding, log_domain,
                    summary_path=os.path.join(info_dir, "throughput.txt"),
                )
                
                # Save throughput.json (machine-readable)
                throughput_data = {
                    "total_keys": summary.total_keys,
                    "total_bits": summary.total_bits,
                    "mean_iat": arrival.mean_iat if summary.has_enough_arrivals else None,
                    "cv_iat": arrival.cv_iat if summary.has_enough_arrivals else None,
                    "rate_keys": arrival.rate_keys if summary.has_enough_arrivals else None,
                    "rate_bits": arrival.rate_bits if summary.has_enough_arrivals else None,
                    "median_throughput": non_overlapping.median_thr if summary.has_enough_arrivals else None,
                    "mean_throughput": non_overlapping.mean_thr if summary.has_enough_arrivals else None,
                    "p05": non_overlapping.p05 if summary.has_enough_arrivals else None,
                    "p95": non_overlapping.p95 if summary.has_enough_arrivals else None,
                }
                with open(os.path.join(info_dir, "throughput.json"), "w") as f:
                    json.dump(throughput_data, f, indent=2)
                
                # Save visits info (derived from simulation_result)
                print(f"  -> Deriving visit info...")
                visit_data = compute_visit_from_simulation(result, S, T)
                
                with open(os.path.join(info_dir, "visits.json"), "w") as f:
                    json.dump(visit_data, f, indent=2)
                
                # Save visits.txt
                with open(os.path.join(info_dir, "visits.txt"), "w") as f:
                    f.write(f"Edge & Node Visit Analysis: {name.upper()}\n")
                    f.write(f"Source: {S}, Target: {T}\n")
                    f.write(f"Variant: {variant}\n")
                    f.write(f"Total packets: {visit_data['total_packets']}\n")
                    f.write(f"{'='*60}\n\n")
                    f.write("Edge Multiplicity (expected visits per packet, ascending):\n")
                    f.write(f"{'-'*40}\n")
                    for edge, mult in sorted(visit_data['edge_multiplicity'].items(), key=lambda x: x[1]):
                        f.write(f"  {edge}: {mult:.4f}\n")
                    f.write(f"\nNode Hitting Probability (excludes {S}, {T}, ascending):\n")
                    f.write(f"{'-'*40}\n")
                    for node, prob in sorted(visit_data['node_hitting_prob'].items(), key=lambda x: x[1]):
                        f.write(f"  {node}: {prob:.4f}\n")
                print(f"  -> Saved visits.json and visits.txt")
            
            # === Pairwise analysis ===
            pairwise_path = os.path.join(raw_dir, "pairwise_results.json")
            if os.path.exists(pairwise_path):
                print(f"\n[{name}/{variant}] Deriving pairwise info...")
                with open(pairwise_path, "r") as f:
                    pairwise_results = json.load(f)
                
                # Compute summary metrics (without packet_data for smaller file)
                pairwise_summary = []
                for r in pairwise_results:
                    pairwise_summary.append({
                        "source": r["source"],
                        "target": r["target"],
                        "throughput_kbps": r["throughput_kbps"],
                        "mean_hops": r["mean_hops"],
                        "packets": r["packets"],
                    })
                
                # Save pairwise.json
                with open(os.path.join(info_dir, "pairwise.json"), "w") as f:
                    json.dump(pairwise_summary, f, indent=2)
                
                # Save pairwise.csv
                with open(os.path.join(info_dir, "pairwise.csv"), "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=["source", "target", "throughput_kbps", "mean_hops", "packets"])
                    writer.writeheader()
                    writer.writerows(pairwise_summary)
                
                # Compute correlation
                import numpy as np
                valid = [(r["throughput_kbps"], r["mean_hops"]) for r in pairwise_summary 
                         if r["throughput_kbps"] > 0 and not np.isnan(r["mean_hops"])]
                if len(valid) > 2:
                    t_vals, h_vals = zip(*valid)
                    mean_t, mean_h = np.mean(t_vals), np.mean(h_vals)
                    cov = sum((t - mean_t) * (h - mean_h) for t, h in valid)
                    std_t = np.std(t_vals) * len(t_vals)
                    std_h = np.std(h_vals) * len(h_vals)
                    pearson_r = cov / (std_t * std_h) if std_t > 0 and std_h > 0 else 0
                else:
                    pearson_r = float('nan')
                
                # Save pairwise.txt
                with open(os.path.join(info_dir, "pairwise.txt"), "w") as f:
                    f.write(f"Pairwise Metrics: {name.upper()}\n")
                    f.write(f"Variant: {variant}\n")
                    f.write(f"{'='*70}\n\n")
                    f.write(f"Correlation (Pearson r) between throughput and hop count: {pearson_r:.4f}\n")
                    f.write(f"  (negative = higher hops -> lower throughput, as expected)\n\n")
                    f.write(f"{'Source':<8} {'Target':<8} {'Throughput':>12} {'Mean hops':>10} {'Packets':>8}\n")
                    f.write(f"{'-'*70}\n")
                    for r in pairwise_summary:
                        f.write(f"{r['source']:<8} {r['target']:<8} {r['throughput_kbps']:>10.2f}  "
                               f"{r['mean_hops']:>10.2f} {r['packets']:>8}\n")
                
                # Derive hitting info from pairwise
                print(f"  -> Deriving hitting info...")
                hitting_results = compute_hitting_from_pairwise(pairwise_results)
                
                with open(os.path.join(info_dir, "hitting.json"), "w") as f:
                    json.dump(hitting_results, f, indent=2)
                
                # Save hitting.txt
                selected_nodes = HEATMAP_NODES.get(name, [])
                with open(os.path.join(info_dir, "hitting.txt"), "w") as f:
                    f.write(f"Max Hitting Node Heatmap: {name.upper()}\n")
                    f.write(f"Variant: {variant}\n")
                    f.write(f"{'='*70}\n\n")
                    f.write(f"{'Source':<8} {'Target':<8} {'MaxHitNode':<12} {'Prob':>8} {'Packets':>8}\n")
                    f.write(f"{'-'*60}\n")
                    for r in hitting_results:
                        f.write(f"{r['source']:<8} {r['target']:<8} {r['max_hitting_node']:<12} "
                               f"{r['max_hitting_prob']:>8.4f} {r['packets']:>8}\n")
                
                print(f"  -> Saved pairwise.json, pairwise.csv, pairwise.txt, hitting.json, hitting.txt")
            
            # === Hop analysis ===
            hop_path = os.path.join(raw_dir, "hop_results.json")
            if os.path.exists(hop_path):
                print(f"\n[{name}/{variant}] Deriving hop info...")
                with open(hop_path, "r") as f:
                    hop_data = json.load(f)
                
                hop_source = hop_data["source"]
                hop_results = hop_data["results"]
                
                # Sort by mean hops
                import numpy as np
                hop_results_sorted = sorted(hop_results, 
                    key=lambda x: x["mean_hops"] if not np.isnan(x["mean_hops"]) else float('inf'))
                
                # Save hops.json
                with open(os.path.join(info_dir, "hops.json"), "w") as f:
                    json.dump({"source": hop_source, "results": hop_results_sorted}, f, indent=2)
                
                # Save hops.csv
                with open(os.path.join(info_dir, "hops.csv"), "w", newline="") as f:
                    writer = csv.DictWriter(f, fieldnames=["destination", "mean_hops", "std_hops", "min_hops", "max_hops", "packets"])
                    writer.writeheader()
                    for r in hop_results_sorted:
                        writer.writerow({
                            "destination": r["destination"],
                            "mean_hops": r["mean_hops"],
                            "std_hops": r["std_hops"],
                            "min_hops": r["min_hops"],
                            "max_hops": r["max_hops"],
                            "packets": r["packets"],
                        })
                
                # Save hops.txt
                with open(os.path.join(info_dir, "hops.txt"), "w") as f:
                    f.write(f"Hop Count Analysis: {name.upper()}\n")
                    f.write(f"Source: {hop_source}\n")
                    f.write(f"Variant: {variant}\n")
                    f.write(f"{'='*60}\n\n")
                    f.write(f"{'Destination':<12} {'Mean':>8} {'Std':>8} {'Min':>6} {'Max':>6} {'Packets':>8}\n")
                    f.write(f"{'-'*60}\n")
                    for r in hop_results_sorted:
                        f.write(f"{r['destination']:<12} {r['mean_hops']:>8.2f} {r['std_hops']:>8.2f} "
                               f"{r['min_hops']:>6} {r['max_hops']:>6} {r['packets']:>8}\n")
                
                print(f"  -> Saved hops.json, hops.csv, hops.txt")
    
    print(f"\n{'='*60}")
    print("All derivations complete!")
    print(f"{'='*60}")


def run_visualizations(args, graphs, variants, output_base: str, dpi: int):
    """Generate charts from info/ data. Reads from info/, writes to charts/."""
    import analysis
    
    for name, nodes_csv, edges_csv in graphs:
        if name not in GRAPH_PAIRS:
            continue
        S, T = GRAPH_PAIRS[name]
        
        output_dir = os.path.join(output_base, name)
        graph_charts_dir = os.path.join(output_dir, "charts")
        os.makedirs(graph_charts_dir, exist_ok=True)
        
        print(f"\n{'='*60}")
        print(f"{name}: Generating charts")
        print(f"{'='*60}")
        
        # --- Combined throughput time series (R/NB/LRV on same plot) ---
        # We generate this once per graph (if all three variants exist).
        combined_series: dict[str, analysis.SlidingWindowSeries] = {}
        combined_cfg: dict | None = None
        variant_to_short = {"random": "R", "nonbacktracking": "NB", "lrv": "LRV"}
        for variant in variants:
            variant_prefix = {"random": "r", "nonbacktracking": "nb", "lrv": "lrv"}[variant]
            raw_dir = os.path.join(output_dir, variant_prefix, "raw")
            config_path = os.path.join(raw_dir, "config.json")
            result_path = os.path.join(raw_dir, "simulation_result.json")
            if not (os.path.exists(config_path) and os.path.exists(result_path)):
                continue
            with open(config_path, "r") as f:
                raw_config = json.load(f)
            result = SimulationResult.load(result_path)

            plot_config = {
                "KEY_SIZE": raw_config["key_size"],
                "NODE_BUFF_KEYS": raw_config["node_buff_keys"],
                "LINK_BUFF_BITS": raw_config["link_buff_bits"],
                "LINKS_EMPTY_AT_START": raw_config["links_empty_at_start"],
                "QKD_SKR": raw_config["qkd_skr"],
                "LATENCY": raw_config["latency"],
                "TICK_INTERVAL": TICK_INTERVAL,
                "WINDOW_SIZE": WINDOW_SIZE,
                "SIM_DURATION": raw_config["sim_duration"],
                "HIST_BIN_WIDTH": HIST_BIN_WIDTH,
                "MIN_KEYS_IN_WINDOW": MIN_KEYS_IN_WINDOW,
                "BURN_IN": BURN_IN,
                "S": S,
                "T": T,
                "VARIANT": variant_to_short[variant],
                "VARIANT_LONG": variant,
                "GRAPH": name,
                "DPI": dpi,
                "nodes_count": raw_config.get("nodes_count", 0),
                "edges_count": raw_config.get("edges_count", 0),
            }

            analyzer = analysis.Analyzer(plot_config)
            sliding = analyzer.compute_sliding_window_metrics(result.arrival_times)
            combined_series[variant_to_short[variant]] = sliding
            combined_cfg = combined_cfg or plot_config

        if combined_cfg is not None and all(k in combined_series for k in ("R", "NB", "LRV")):
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(1, 1, figsize=(7, 5))
            # Savitzky–Golay smoothing parameters for combined plot only.
            # (Odd window length in samples; polyorder < window length)
            combined_cfg = dict(combined_cfg)
            combined_cfg.setdefault("SG_WINDOW", 41)
            combined_cfg.setdefault("SG_POLY", 3)
            analysis.plot_sliding_window_combined(ax, combined_series, combined_cfg)
            fig.tight_layout()
            out_path = os.path.join(graph_charts_dir, "throughput_combined.png")
            fig.savefig(out_path, dpi=dpi, facecolor="white", edgecolor="none")
            plt.close(fig)
            print(f"\n[{name}] Combined throughput plot saved to {out_path}")

        for variant in variants:
            variant_prefix = {"random": "r", "nonbacktracking": "nb", "lrv": "lrv"}[variant]
            variant_dir = os.path.join(output_dir, variant_prefix)
            raw_dir = os.path.join(variant_dir, "raw")
            info_dir = os.path.join(variant_dir, "info")
            charts_dir = os.path.join(variant_dir, "charts")
            os.makedirs(charts_dir, exist_ok=True)
            
            # Load config
            config_path = os.path.join(raw_dir, "config.json")
            if not os.path.exists(config_path):
                print(f"  [{variant}] No config found at {config_path}")
                continue
            
            with open(config_path, "r") as f:
                raw_config = json.load(f)
            
            # === Throughput charts ===
            result_path = os.path.join(raw_dir, "simulation_result.json")
            if os.path.exists(result_path):
                print(f"\n[{name}/{variant}] Generating throughput charts...")
                result = SimulationResult.load(result_path)
                
                plot_config = {
                    "KEY_SIZE": raw_config["key_size"],
                    "NODE_BUFF_KEYS": raw_config["node_buff_keys"],
                    "LINK_BUFF_BITS": raw_config["link_buff_bits"],
                    "LINKS_EMPTY_AT_START": raw_config["links_empty_at_start"],
                    "QKD_SKR": raw_config["qkd_skr"],
                    "LATENCY": raw_config["latency"],
                    "TICK_INTERVAL": TICK_INTERVAL,
                    "WINDOW_SIZE": WINDOW_SIZE,
                    "SIM_DURATION": raw_config["sim_duration"],
                    "HIST_BIN_WIDTH": HIST_BIN_WIDTH,
                    "MIN_KEYS_IN_WINDOW": MIN_KEYS_IN_WINDOW,
                    "BURN_IN": BURN_IN,
                    "S": S,
                    "T": T,
                    "VARIANT": {"random": "R", "nonbacktracking": "NB", "lrv": "LRV"}[variant],
                    "VARIANT_LONG": variant,
                    "GRAPH": name,
                    "DPI": dpi,
                    "nodes_count": raw_config.get("nodes_count", 0),
                    "edges_count": raw_config.get("edges_count", 0),
                }
                
                arrival_times = result.arrival_times
                print(f"  # of arrivals: {len(arrival_times)}")
                
                analyzer = analysis.Analyzer(plot_config)
                summary = analyzer.compute_summary(arrival_times)
                non_overlapping = analyzer.compute_non_overlapping_throughput(arrival_times)
                sliding = analyzer.compute_sliding_window_metrics(arrival_times)
                
                plot_all(
                    summary, sliding, non_overlapping, plot_config,
                    output_path=os.path.join(charts_dir, "throughput.png"),
                    output_dir=charts_dir,
                    show=False,
                )
            
            # === Pairwise heatmaps ===
            pairwise_info_path = os.path.join(info_dir, "pairwise.json")
            if name in HEATMAP_NODES and os.path.exists(pairwise_info_path):
                print(f"\n[{name}/{variant}] Generating pairwise heatmaps...")
                with open(pairwise_info_path, "r") as f:
                    pairwise_data = json.load(f)
                visualize_pairwise_heatmaps(
                    pairwise_data,
                    selected_nodes=HEATMAP_NODES[name],
                    output_dir=charts_dir,
                    graph_name=name,
                    variant=variant,
                    dpi=dpi,
                )
                
                # Hitting heatmap
                hitting_info_path = os.path.join(info_dir, "hitting.json")
                if os.path.exists(hitting_info_path):
                    print(f"  -> Generating hitting heatmap...")
                    with open(hitting_info_path, "r") as f:
                        hitting_data = json.load(f)
                    visualize_hitting_heatmap(
                        hitting_data,
                        selected_nodes=HEATMAP_NODES[name],
                        output_dir=charts_dir,
                        graph_name=name,
                        variant=variant,
                        dpi=dpi,
                    )
            
            # === Hop count chart ===
            hops_info_path = os.path.join(info_dir, "hops.json")
            if os.path.exists(hops_info_path):
                print(f"\n[{name}/{variant}] Generating hop count chart...")
                with open(hops_info_path, "r") as f:
                    hops_data = json.load(f)
                visualize_hop_counts(
                    hops_data["results"],
                    source=hops_data["source"],
                    output_dir=charts_dir,
                    graph_name=name,
                    variant=variant,
                    dpi=dpi,
                )
            
            # === Visit charts ===
            visits_info_path = os.path.join(info_dir, "visits.json")
            if os.path.exists(visits_info_path):
                print(f"\n[{name}/{variant}] Generating visit charts...")
                with open(visits_info_path, "r") as f:
                    visits_data = json.load(f)
                visualize_edge_node_visits(
                    visits_data,
                    output_dir=charts_dir,
                    graph_name=name,
                    variant=variant,
                    dpi=dpi,
                )
    
    print(f"\n{'='*60}")
    print("All charts complete!")
    print(f"{'='*60}")


def plot_all(
    summary,
    sliding,
    non_overlapping,
    config: dict,
    output_path: str | None = "throughput.png",
    output_dir: str = "out",
    show: bool = True,
):
    import analysis
    
    if not summary.has_enough_arrivals:
        return None, None

    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    analysis.plot_sliding_window(axes[0], sliding, config)
    analysis.plot_non_overlapping_histogram(axes[1], non_overlapping, config)

    plt.suptitle(
        f"{config['GRAPH']} | {config['VARIANT']} | "
        f"burn-in={config['BURN_IN']}s, sim={config['SIM_DURATION']}s",
        fontsize=12,
    )
    dpi = config.get("DPI", 150)
    plt.tight_layout()
    if output_path:
        plt.savefig(output_path, dpi=dpi)
    if show:
        plt.show()
    if output_path:
        print(f"  Plot saved to {output_path}")

    os.makedirs(output_dir, exist_ok=True)
    _save_single_plot(
        lambda ax: analysis.plot_sliding_window(ax, sliding, config),
        os.path.join(output_dir, "throughput_time_series.png"),
        dpi=dpi,
    )
    _save_single_plot(
        lambda ax: analysis.plot_non_overlapping_histogram(ax, non_overlapping, config),
        os.path.join(output_dir, "throughput_freq_distribution.png"),
        dpi=dpi,
    )
    return fig, axes


def _save_single_plot(plot_fn, path: str, dpi: int = 150) -> None:
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 1, figsize=(6, 5))
    plot_fn(ax)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi)
    plt.close(fig)


def compute_hitting_from_pairwise(pairwise_results: list) -> list:
    """Compute max hitting node for each pair from pairwise packet data."""
    from collections import Counter
    
    results = []
    for r in pairwise_results:
        src, tgt = r["source"], r["target"]
        packet_data = r.get("packet_data", [])
        
        if not packet_data:
            results.append({
                "source": src,
                "target": tgt,
                "max_hitting_node": "",
                "max_hitting_prob": float('nan'),
                "packets": 0,
            })
            continue
        
        node_hit_counts = Counter()
        for p in packet_data:
            visited = set(p["history"])
            for node in visited:
                if node != src and node != tgt:
                    node_hit_counts[node] += 1
        
        if node_hit_counts:
            best_node = max(node_hit_counts.keys(), key=lambda n: node_hit_counts[n])
            best_prob = node_hit_counts[best_node] / len(packet_data)
        else:
            best_node = "-"
            best_prob = 0
        
        results.append({
            "source": src,
            "target": tgt,
            "max_hitting_node": best_node,
            "max_hitting_prob": best_prob,
            "packets": len(packet_data),
        })
    
    return results


def compute_visit_from_simulation(result: SimulationResult, source: str, target: str) -> dict:
    """Compute edge multiplicity and node hitting probability from simulation result."""
    from collections import Counter
    
    packets = result.packets
    total_packets = len(packets)
    
    if total_packets == 0:
        return {
            "source": source,
            "target": target,
            "total_packets": 0,
            "edge_multiplicity": {},
            "node_hitting_prob": {},
        }
    
    edge_visit_counts = Counter()
    node_hit_counts = Counter()
    
    for p in packets:
        history = p["history"]
        visited_nodes = set()
        
        # Count edge traversals
        for k in range(len(history) - 1):
            edge = tuple(sorted([history[k], history[k + 1]]))
            edge_visit_counts[edge] += 1
        
        # Count node visits (excluding source and target)
        for node in history:
            if node != source and node != target:
                visited_nodes.add(node)
        for node in visited_nodes:
            node_hit_counts[node] += 1
    
    edge_multiplicity = {f"{e[0]}-{e[1]}": c / total_packets for e, c in edge_visit_counts.items()}
    node_hitting_prob = {n: c / total_packets for n, c in node_hit_counts.items()}
    
    return {
        "source": source,
        "target": target,
        "total_packets": total_packets,
        "edge_multiplicity": edge_multiplicity,
        "node_hitting_prob": node_hitting_prob,
    }


def visualize_pairwise_heatmaps(
    results: list,
    selected_nodes: list,
    output_dir: str,
    graph_name: str,
    variant: str,
    dpi: int = 150,
) -> None:
    """Generate heatmaps from pairwise data (reads from info/)."""
    import matplotlib.pyplot as plt
    import numpy as np
    
    n = len(selected_nodes)
    throughput_matrix = np.full((n, n), np.nan)
    hopcount_matrix = np.full((n, n), np.nan)
    
    node_to_idx = {node: i for i, node in enumerate(selected_nodes)}
    
    for r in results:
        i = node_to_idx.get(r["source"])
        j = node_to_idx.get(r["target"])
        if i is not None and j is not None:
            throughput_matrix[i, j] = r["throughput_kbps"]
            hopcount_matrix[i, j] = r["mean_hops"]
    
    # Throughput heatmap
    _plot_heatmap(
        throughput_matrix, selected_nodes,
        title=f"{graph_name.upper()} throughput heatmap ({variant})",
        cbar_label="Throughput (kbit/s)",
        output_path=os.path.join(output_dir, "throughput_heatmap.png"),
        cmap="magma", fmt=".1f", dpi=dpi
    )
    
    # Hop count heatmap
    _plot_heatmap(
        hopcount_matrix, selected_nodes,
        title=f"{graph_name.upper()} hop count heatmap ({variant})",
        cbar_label="Mean hop count",
        output_path=os.path.join(output_dir, "hopcount_heatmap.png"),
        cmap="viridis", fmt=".1f", dpi=dpi
    )


def _plot_heatmap(
    matrix, labels: list, title: str, cbar_label: str,
    output_path: str, cmap: str = "magma", fmt: str = ".1f", dpi: int = 150
) -> None:
    """Helper to plot a heatmap."""
    import matplotlib.pyplot as plt
    import numpy as np

    n = len(labels)
    fig, ax = plt.subplots(figsize=(10, 8))

    masked_data = np.ma.masked_invalid(matrix)

    colormap = plt.colormaps.get_cmap(cmap).copy()
    colormap.set_bad(color='#1a1a2e')

    im = ax.imshow(masked_data, cmap=colormap, aspect='equal')

    cbar = ax.figure.colorbar(im, ax=ax, shrink=0.8)
    cbar.ax.set_ylabel(cbar_label, rotation=-90, va="bottom", fontsize=11)

    ax.set_xticks(np.arange(n))
    ax.set_yticks(np.arange(n))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_yticklabels(labels, fontsize=9)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")

    ax.set_xlabel("Destination", fontsize=12)
    ax.set_ylabel("Source", fontsize=12)
    ax.set_title(title, fontsize=14, pad=10)

    for i in range(n):
        for j in range(n):
            if i != j and not np.isnan(matrix[i, j]):
                val = matrix[i, j]
                text_color = "white" if val < masked_data.max() * 0.6 else "black"
                ax.text(j, i, f"{val:{fmt}}", ha="center", va="center",
                       color=text_color, fontsize=9)

    plt.tight_layout()
    plt.savefig(output_path, dpi=dpi, facecolor='white', edgecolor='none')
    plt.close(fig)
    print(f"  Heatmap saved to {output_path}")


def visualize_hop_counts(
    results: list,
    source: str,
    output_dir: str,
    graph_name: str,
    variant: str,
    dpi: int = 150,
) -> None:
    """Generate hop count bar chart from results (reads from info/)."""
    import matplotlib.pyplot as plt
    import numpy as np
    
    # Results should already be sorted from info phase
    fig, ax = plt.subplots(figsize=(6, 5))
    
    dests = [r["destination"] for r in results]
    means = [r["mean_hops"] for r in results]
    stds = [r["std_hops"] for r in results]
    
    colors = plt.cm.viridis(np.linspace(0, 1, len(dests)))
    
    ax.bar(range(len(dests)), means, yerr=stds, capsize=2,
           color=colors, edgecolor='white', linewidth=0.5,
           error_kw={'ecolor': 'gray', 'alpha': 0.6, 'capthick': 1})
    
    ax.set_xticks(range(len(dests)))
    ax.set_xticklabels(dests, rotation=90, ha='center', fontsize=6)
    ax.set_xlabel("Destination", fontsize=10)
    ax.set_ylabel("Expected hop count", fontsize=10)
    ax.set_title(f"{graph_name.upper()} hop counts from {source} ({variant}, ±1σ)", fontsize=11)
    ax.grid(True, axis='y', alpha=0.3)
    ax.set_axisbelow(True)
    ax.set_ylim(bottom=0)
    
    plt.tight_layout()
    png_path = os.path.join(output_dir, "hop_counts.png")
    plt.savefig(png_path, dpi=dpi, facecolor='white', edgecolor='none')
    plt.close(fig)
    print(f"  Chart saved to {png_path}")


def visualize_edge_node_visits(
    data: dict,
    output_dir: str,
    graph_name: str,
    variant: str,
    dpi: int = 150,
) -> None:
    """Generate edge multiplicity and node hitting charts (reads from info/)."""
    import matplotlib.pyplot as plt
    import numpy as np
    
    source = data["source"]
    target = data["target"]
    total_packets = data["total_packets"]
    edge_multiplicity = data["edge_multiplicity"]
    node_hitting_prob = data["node_hitting_prob"]
    
    if total_packets == 0:
        print("  No packets, skipping visualization")
        return
    
    # Edge multiplicity chart
    fig, ax = plt.subplots(figsize=(6, 5))
    edges_sorted = sorted(edge_multiplicity.keys(), key=lambda e: edge_multiplicity[e])
    multiplicities = [edge_multiplicity[e] for e in edges_sorted]
    colors = plt.cm.plasma(np.linspace(0, 1, len(edges_sorted)))
    ax.bar(range(len(multiplicities)), multiplicities, color=colors, edgecolor='white', linewidth=0.5)
    ax.set_xlabel("Edge (sorted ascending)", fontsize=10)
    ax.set_ylabel("Expected visits per packet", fontsize=10)
    ax.set_title(f"{graph_name.upper()} edge multiplicity {source}→{target} ({variant})", fontsize=11)
    ax.grid(True, axis='y', alpha=0.3)
    ax.set_axisbelow(True)
    plt.tight_layout()
    png_path = os.path.join(output_dir, "edge_multiplicity.png")
    plt.savefig(png_path, dpi=dpi, facecolor='white', edgecolor='none')
    plt.close(fig)
    print(f"  Edge multiplicity chart saved to {png_path}")
    
    # Node hitting chart
    fig, ax = plt.subplots(figsize=(6, 5))
    nodes_sorted = sorted(node_hitting_prob.keys(), key=lambda n: node_hitting_prob[n])
    probs = [node_hitting_prob[n] for n in nodes_sorted]
    colors = plt.cm.viridis(np.linspace(0, 1, len(nodes_sorted)))
    ax.bar(range(len(nodes_sorted)), probs, color=colors, edgecolor='white', linewidth=0.5)
    ax.set_xticks(range(len(nodes_sorted)))
    ax.set_xticklabels(nodes_sorted, rotation=90, ha='center', fontsize=6)
    ax.set_xlabel("Node (sorted ascending)", fontsize=10)
    ax.set_ylabel("Hitting probability", fontsize=10)
    ax.set_title(f"{graph_name.upper()} node hitting {source}→{target} ({variant})", fontsize=11)
    ax.grid(True, axis='y', alpha=0.3)
    ax.set_axisbelow(True)
    ax.set_ylim(0, 1.05)
    plt.tight_layout()
    png_path = os.path.join(output_dir, "node_hitting.png")
    plt.savefig(png_path, dpi=dpi, facecolor='white', edgecolor='none')
    plt.close(fig)
    print(f"  Node hitting chart saved to {png_path}")


def visualize_hitting_heatmap(
    results: list,
    selected_nodes: list,
    output_dir: str,
    graph_name: str,
    variant: str,
    dpi: int = 150,
) -> None:
    """Generate hitting probability heatmap (reads from info/)."""
    import matplotlib.pyplot as plt
    import numpy as np
    
    n = len(selected_nodes)
    max_hitting_node = [['' for _ in range(n)] for _ in range(n)]
    max_hitting_prob = np.full((n, n), np.nan)
    
    node_to_idx = {node: i for i, node in enumerate(selected_nodes)}
    
    for r in results:
        i = node_to_idx.get(r["source"])
        j = node_to_idx.get(r["target"])
        if i is not None and j is not None:
            max_hitting_node[i][j] = r["max_hitting_node"]
            max_hitting_prob[i, j] = r["max_hitting_prob"]
    
    # Create heatmap
    fig, ax = plt.subplots(figsize=(10, 8))
    
    masked_data = np.ma.masked_invalid(max_hitting_prob)
    cmap = plt.colormaps.get_cmap("YlOrRd").copy()
    cmap.set_bad(color='#1a1a2e')
    
    im = ax.imshow(masked_data, cmap=cmap, aspect='equal', vmin=0, vmax=1)
    
    cbar = ax.figure.colorbar(im, ax=ax, shrink=0.8)
    cbar.ax.set_ylabel("Hitting probability", rotation=-90, va="bottom", fontsize=11)
    
    ax.set_xticks(np.arange(n))
    ax.set_yticks(np.arange(n))
    ax.set_xticklabels(selected_nodes, fontsize=9)
    ax.set_yticklabels(selected_nodes, fontsize=9)
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
    
    ax.set_xlabel("Destination", fontsize=12)
    ax.set_ylabel("Source", fontsize=12)
    ax.set_title(f"{graph_name.upper()} max hitting node ({variant})", fontsize=14, pad=10)
    
    for i in range(n):
        for j in range(n):
            if i != j and max_hitting_node[i][j]:
                prob = max_hitting_prob[i, j]
                if not np.isnan(prob):
                    text_color = "white" if prob > 0.5 else "black"
                    ax.text(j, i, f"{max_hitting_node[i][j]}\n{prob:.2f}",
                           ha="center", va="center", color=text_color, fontsize=9)
    
    plt.tight_layout()
    png_path = os.path.join(output_dir, "hitting_heatmap.png")
    plt.savefig(png_path, dpi=dpi, facecolor='white', edgecolor='none')
    plt.close(fig)
    print(f"  Heatmap saved to {png_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Random walk key relaying throughput simulation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  pypy3 throughput.py --mode sim           # Fast simulation with PyPy (raw/)
  python3 throughput.py --mode info        # Derive info from raw data (info/)
  python3 throughput.py --mode charts      # Generate charts (charts/)
  python3 throughput.py --mode all         # All phases (default)
  python3 throughput.py --mode sim --quick # Quick test run
        """
    )
    parser.add_argument(
        "--mode",
        choices=["sim", "info", "charts", "all"],
        default="all",
        help="sim=simulation, info=derivation, charts=visualization, all=all phases (default: all)"
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick mode: shorter simulations (10s), lower DPI (72), output to quick/"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Number of parallel workers for simulations (default: CPU count)"
    )
    parser.add_argument(
        "--no-parallel",
        action="store_true",
        help="Disable parallel execution (useful for debugging)"
    )
    args = parser.parse_args()

    # Apply quick mode settings
    if args.quick:
        QUICK_MODE = True
        OUTPUT_BASE = "quick"
        DPI = 72
        HEATMAP_SIM_DURATION = 10.0
        HOP_SIM_DURATION = 10.0
        SIM_DURATION = 100.0
        print("*** QUICK MODE: shorter simulations, lower quality images ***\n")
    else:
        OUTPUT_BASE = "out"
        DPI = 150
        HEATMAP_SIM_DURATION = 100.0
        HOP_SIM_DURATION = 100.0
        SIM_DURATION = 1000.0

    graphs = [
        ("geant", "graphs/geant/geant_nodes.csv", "graphs/geant/geant_edges.csv"),
        ("nsfnet", "graphs/nsfnet/nsfnet_nodes.csv", "graphs/nsfnet/nsfnet_edges.csv"),
        ("secoqc", "graphs/secoqc/secoqc_nodes.csv", "graphs/secoqc/secoqc_edges.csv"),
    ]

    variants = ["random", "nonbacktracking", "lrv"]

    if args.mode in ("sim", "all"):
        print(f"\n{'#'*60}")
        print("# SIMULATION PHASE (raw/)")
        print(f"{'#'*60}")
        run_all_simulations(args, graphs, variants, OUTPUT_BASE, SIM_DURATION)

    if args.mode in ("info", "all"):
        print(f"\n{'#'*60}")
        print("# DERIVATION PHASE (info/)")
        print(f"{'#'*60}")
        run_derivations(graphs, variants, OUTPUT_BASE)

    if args.mode in ("charts", "all"):
        print(f"\n{'#'*60}")
        print("# VISUALIZATION PHASE (charts/)")
        print(f"{'#'*60}")
        run_visualizations(args, graphs, variants, OUTPUT_BASE, DPI)
