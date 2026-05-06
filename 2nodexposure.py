from helpers.graphs import read_geant_graph
from tqdm import tqdm
from subprocess import check_output
from concurrent.futures import ThreadPoolExecutor, as_completed
import networkx as nx
import re
import json

graph = read_geant_graph()
nodes = list(graph.nodes())

check_output(["make", "./build/hops"], cwd="cpp")


def compute_uv_exposures(pair):
    u, v = pair
    uv_exposures = []
    skipped_pairs = []

    without_uv = graph.copy()
    without_uv.remove_nodes_from([u, v])

    for src in nodes:
        for tgt in nodes:
            if src == tgt: continue

            # if src or tgt is u or v, then skip
            if src == u or src == v or tgt == u or tgt == v: continue

            # if removing u, v disconnects src, tgt, then skip u,v
            if not nx.has_path(without_uv, src, tgt):
                skipped_pairs.append((src, tgt))
                continue

            # run the simulation from src to tgt with cartel {u,v}
            cmd = [
                "./cpp/build/hops",
                "-s", str(src),
                "-t", str(tgt),
                "-w", "HS",
                "-e", "./graphs/geant/edges.csv",
                "-n", "1000",
                "--cartel", f"{u},{v}",
            ]
            output = check_output(cmd).decode("utf-8")

            exposure = re.search(r"cartel_hit_prob_lerw: ([0-9.]+)", output).group(1)
            uv_exposures.append({"src": src, "tgt": tgt, "exposure": float(exposure)})

    return {"u": u, "v": v, "exposures": uv_exposures}


pairs = [(u, v) for u in nodes for v in nodes if u < v]

exposures = []
with ThreadPoolExecutor(max_workers=12) as executor:
    futures = [executor.submit(compute_uv_exposures, pair) for pair in pairs]
    for future in tqdm(as_completed(futures), total=len(futures), desc="Processing malicious node pairs"):
        exposures.append(future.result())

# save the exposures to a json file
with open("exposures.json", "w") as f:
    json.dump(exposures, f)