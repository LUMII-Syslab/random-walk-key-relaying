Use great-circle distance (Haversine) between the source/target node coordinates, then write it back into the edge list as a numeric Weight column (Gephi will pick it up).

```bash
python3 distances.py nodes.csv edges.csv edges_weighted.csv
```
