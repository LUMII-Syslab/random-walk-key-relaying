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

For each source, scouts are emitted at a fixed rate and do a random walk.

At each hop arrival over edge \((sender,receiver)\):

- **Drop on return-to-source** (after leaving).
- **Drop on wait-limit**: if `observe_wait_s(time) > max_wait_time_s`, drop immediately.
- Otherwise, receiver may **accept** with probability `consume(...)` (depends on hop count + `buffered_keys[src,tgt]` vs `watermark_sz`).

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

For each ordered pair \((src,tgt)\), received chunks are grouped into windows of size `block_chunks` (`--block-chunks`, default: 32).
At block close:

- Choose a **worst-case cartel** of size \(m\in\{0,1,2,3\}\) that maximizes how many chunks in the block traverse *any* cartel member (excluding endpoints).
- Let `max_seen` be that maximum coverage count.
- Define \(h = block\_chunks - max\_seen\).
- Extract \(h\) keys (0 if \(h\le 0\)).

#### Cartel size selection

Cartel size is derived from **local vertex connectivity** \(\kappa(src,tgt)\), computed on demand via split-vertex max flow in `Graph::vertex_connectivity`:

- \(m = \min(\texttt{--cartel-size-limit},\ \max(0,\ \kappa(src,tgt)-1))\) with default and maximum limit 3.

Intermediate vertices \(x \notin \{s,t\}\) are split into \(x_1 \to x_2\) (capacity 1); each undirected edge \(\{u,v\}\) becomes directed arcs \((u_2,v_1)\) and \((v_2,u_1)\) (capacity 1). Max \(s \to t\) flow equals \(\kappa(s,t)\).

#### Parameters (current)

- `--watermark-sz <int>`: **buffer watermark** used only by `consume(...)` (accept/drop dynamics), not the block size.
- `--block-chunks <int>`: chunks per extraction block/window (default: 16).

### Output

- `keys <h> <src> <tgt> <cartel_nodes_or_-> <max_seen> vconn=<k> cartel_sz=<m>` (printed when a block closes in `--verbose` mode)
- `Halted at <t> seconds` (when `--halt-at-keys` condition is satisfied)

