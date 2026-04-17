# `scouted` (`cpp/scouted.cpp`)

Discrete-event simulation of **scout-based key relaying** on an undirected graph.

### Time + links

- **Classical hop latency**: \(\Delta = 5\) ms (`kClassicLatencyS`).
- Each undirected link has a **QKD queue** with constant SKR.
  - **Chunk size**: 256 bits (`kChunkBits`)
  - **SKR**: 1000 bits/s (`kQkdSkrBitsPerS`)
  - **Service time**: \(T_\text{chunk} = 256/1000 = 0.256\) s
- `observe_wait_s(t)` returns the current queue backlog in seconds (what a *new* reservation would wait).
- `enqueue_and_get_ready_time(t)` reserves one chunk on that link and returns the time when that reservation becomes ready.

### Scouts

For each source, scouts are emitted at `scout_rate_per_s` and do a random walk (`--rw-variant`).

At each hop arrival over edge \((sender,receiver)\):

- **Drop on return-to-source** (after leaving).
- **Drop on wait-limit**: if `observe_wait_s(time) > max_wait_time_s`, drop immediately.
- Otherwise, receiver may **accept** with probability `consume_probability(...)` (depends on hop count + `buffered_keys[receiver][src]` vs `watermark_sz`).

On acceptance at `tgt`:

- Compute `path = loop_erase_path(walk_nodes)` (simple \(src \to tgt\)).
- Return phase reserves **one chunk** on each hop of `path` (walking back \(tgt \to src\)), storing per-hop ready-times.

### Chunk send time

After the scout returns to `src`, one classical chunk is sent along `path`.  
During the return phase, each hop reservation observes a queue wait (in seconds).  
Let `max_return_wait_s` be the **maximum** of those waits. The source sends the chunk at:

\[
send\_time = now + max\_return\_wait\_s.
\]

`max_wait_time_s` is **only** a forward-walk drop rule; it does not constrain how long the source may wait to emit.

### Blocks and extracted keys

For each ordered pair \((src,tgt)\), received chunks are grouped into windows of size `block_chunks`.
At block close:

- Choose an **optimal cartel** of size \(m\in\{0,1,2\}\) (`--cartel-size`) that maximizes how many paths in the block include it (excluding endpoints).
- Let `max_seen` be that maximum coverage count.
- Define \(h = block\_chunks - max\_seen\).
- Extract `min(max_block_keys, h)` keys (0 if \(h\le 0\)).

### Output

- `recv_chunk time src tgt <path...>`
- `key_establ time src tgt key_count`

