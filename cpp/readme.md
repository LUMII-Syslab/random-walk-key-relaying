# Running C++ simulations

```bash
make
./build/hops -s MAR -t TIR -w HS -e ../graphs/geant/edges.csv -n 256 --record-paths
```

## Proactive mode simulation

This is for evaluation of the second publication.


QKD network is configured with constant 1 kbits/s secure key rate (SKR) on links.

There is one or multiple source nodes emitting chunks without specified target.

At the beginning 

The source nodes emit chunks continously.

Each node has a FIFO relay buffer. For now we assume that it has a size of at most 100.
The relay buffer is source-specific.