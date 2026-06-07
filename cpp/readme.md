# Running C++ simulations

```bash
make
./build/hops -s MAR -t TIR -w HS -g geant -n 256 --record-paths
```

Binaries:

| Target | Role |
|--------|------|
| `hops` | Monte Carlo hop-count stats for s→t random walks |
| `exposure` | Cartel exposure on loop-erased walks (inclusion–exclusion) |
| `scouted` | Scout-based key relaying sim with block honesty / cartel extraction |
| `tput` | Known s→t chunk throughput under QKD link queues |

Walk tools (`hops`, `exposure`, `tput`) use `-g` / `--graph` (`nsfnet`, `geant`, or edges CSV path; default `geant`).

Scout simulator details: [`scouted.md`](scouted.md).
