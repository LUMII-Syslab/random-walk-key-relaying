# Running C++ simulations

```bash
make
./build/hops -s MAR -t TIR -w HS -e ../graphs/geant/edges.csv -n 256 --record-paths
```

## Proactive mode simulation

This is for evaluation of the second publication.


QKD network is configured with constant 1 kbits/s secure key rate (SKR) on links.

There is one or multiple source nodes emitting chunks without specified target.

At the beginning, each source node fills its own send window (in-flight limit), then keeps emitting new chunks as ACKs arrive.

### Internal event model (C++ `build/proactive`)

- **Chunk size**: 256 bits
- **QKD SKR**: 1000 bits/s per link
- **Classic latency**: 5 ms (one-way)
- **TTL bounds (unknown-target mode)**: min=1, max=100 (fixed)

Each chunk hop is modeled with the following internal events:

- **`OtpAvailable`**: the sender can OTP-encrypt and send once enough link key bits are available (waiting time comes from `LinkState::reserve`).
- **`ChunkReceived`**: the receiver gets the chunk after an additional **+5 ms**.
- **`AckResponse`**: after processing the chunk, the receiver sends an ACK back after an additional **+5 ms**; when the source receives the ACK it frees one send-window slot and may emit a new chunk.

### Drop / forward / consume logic at the receiver

When node **B** receives a chunk originating from source **A**:

- **Drop** if:
  - the chunk returns to its origin (**receiver == A**) at a later hop (loop-prevention), or
  - B's **per-source FIFO relay buffer** for source A is full (capacity is `--relay-buff-sz`, default 100).
- **Consume** with probability \(p\) (unknown-target mode), based on the paper formula:
  \[
    p = 1 - b \cdot t_{\text{remaining}},
  \]
  where \(b = \min(1, |R_t[A]|/\text{watermark})\) and \(t_{\text{remaining}} = (maxTTL - i)/maxTTL\).
- **Forward** otherwise (continues the random walk).

### Reported output events

The simulator reports a time-sorted list of events of two types (as parsed by `helpers/compute.py`):

- `recv_chunk time src tgt [path...]`
- `key_establ time src tgt key_count`