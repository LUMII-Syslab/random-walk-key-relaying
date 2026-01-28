#!/usr/bin/env python3
import math
import sys
import pandas as pd

R_KM = 6371.0088  # mean Earth radius in km

def haversine_km(lat1, lon1, lat2, lon2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R_KM * math.atan2(math.sqrt(a), math.sqrt(1 - a))

def main(nodes_path, edges_path, out_path):
    nodes = pd.read_csv(nodes_path)
    edges = pd.read_csv(edges_path)

    # Expect: nodes has Id, Latitude, Longitude (Label optional)
    nodes = nodes.set_index("Id")[["Latitude", "Longitude"]]

    def edge_weight(row):
        s, t = row["Source"], row["Target"]
        if s not in nodes.index or t not in nodes.index:
            raise KeyError(f"Missing coordinates for node(s): {s}, {t}")
        lat1, lon1 = nodes.loc[s, "Latitude"], nodes.loc[s, "Longitude"]
        lat2, lon2 = nodes.loc[t, "Latitude"], nodes.loc[t, "Longitude"]
        return haversine_km(lat1, lon1, lat2, lon2)

    edges["Weight"] = edges.apply(edge_weight, axis=1).round(1)  # km, 0.1 km precision
    edges.to_csv(out_path, index=False)

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: distances.py nodes.csv edges.csv edges_weighted.csv", file=sys.stderr)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
