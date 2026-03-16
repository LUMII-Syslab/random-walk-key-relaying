from helpers.compute import ThroughputStats, compute_tput_stats
from helpers.utils import read_edge_list_csv, graphs_dir
from tqdm import tqdm
from statistics import mean

geant = read_edge_list_csv(graphs_dir / "geant" / "edges.csv")


for s in tqdm(geant.nodes()):
        for t in geant.nodes():
            if s==t: continue
            res = compute_tput_stats(params=ThroughputStats.TputSimParams(
                g=geant,
                chunk_size_bits=256,
                latency_s=0.05,
                link_buff_sz_bits=10**9,
                print_arrival_times=False,
                qkd_skr_bits_per_s=1000,
                relay_buffer_sz_chunks=10**9,
                sim_duration_s=1000,
                src=s,
                tgt=t,
                var="HS",
                erase_loops=False,
            ))
            print(f"{s} {t} {res.mean_tput_bits} {int(res.mean_tput_bits*1000*100/(res.emitted_chunks*256))}%", flush=True)
        print(f"{s} {mean(tputs)}", flush=True)
        exit(0)