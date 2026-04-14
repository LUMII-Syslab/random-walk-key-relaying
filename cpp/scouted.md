# `scouted`: protocol simulated in `scouted.cpp`

This document describes the **protocol model** simulated by `cpp/scouted.cpp` (“scouted”), at the level of events, state variables, and security/key-extraction accounting.

The simulator is a **discrete-event** model of *key relaying with scouting*, where:

- A **scout** performs a random walk until it is *accepted* by some node.
- The accepting node loop-erases the walk into a simple **path** $(source \to target)$.
- The accepting node **checks congestion** along the loop-erased path; if OK, it “returns” the scout by **reserving** one chunk worth of QKD key on each hop’s link queue.
- When the source has enough one-time-pad (OTP) material available hop-by-hop, it sends a classical **chunk** along that fixed path.
- After `block_chunks` chunks for a $(src,tgt)$ pair, the target computes how many keys can be extracted under an **optimal cartel adversary** of size $m \in 0,1,2$.

The code is the source of truth; the goal here is to explain *what is being simulated* and how to interpret its output/diagnostics.

## Entities and time model

- **Nodes**: vertices of an undirected graph.
- **Links**: undirected edges; each link has a QKD “key production” process modeled as a **FIFO queue** of reserved chunk-keys.
- **Events**: processed in non-decreasing simulation time.
- **Classical propagation latency**: every hop traversal of scouts and chunks costs a fixed
$\Delta = 5\text{ ms}$ (see `kClassicLatencyS`).

The simulator does **not** model quantum transmission explicitly; it models the *availability* of key material as time-varying capacity at each link via a queue and a fixed secret key rate.

## Link QKD model (queue + secret key rate)

Each undirected link $(u,v)$ has a queue state representing **reserved** key consumption for future chunks.

- **Chunk size**: `kChunkBits = 256` bits.
- **Secret key rate (SKR)**: `kQkdSkrBitsPerS = 1000` bits/s (1 kbit/s).
- **Service time per reserved chunk**:

$$T_\text{chunk} = \frac{\text{chunk bits}}{\text{SKR}} = \frac{256}{1000}\text{ s} = 0.256\text{ s}.$$

### Observed waiting time

At any time $t$, the simulator can “observe” a link’s waiting time as the current **backlog time**:

- `observe_wait_s(t)` returns approximately
$(\text{queued chunks}) \times T_\text{chunk}$,
with queueing interpreted as “how long until a new reservation would be ready if enqueued now”.

### Reservation on return

When a scout is accepted, the target returns it by reserving exactly **one chunk** worth of key on **each link** of the chosen loop-erased path:

- `enqueue_and_get_ready_time(t)` appends one chunk reservation to the link’s queue and returns the **ready time** $t_\text{ready}$ for that reservation.

This reservation is the mechanism that later allows the source to decide when a classical chunk can be sent such that hop $i$ has key material ready *by the time the chunk reaches that hop*.

## Scout protocol (forward walk, accept/drop, return reservations)

Each source emits scouts at rate `scout_rate_per_s` (per source).

### Forward random walk

A scout carries:

- `src`: its source node.
- `hops`: number of hops taken so far.
- `walk_nodes`: the visited node sequence (including repeats).
- `token`: a random-walk token (variant chosen by `--rw-variant`), used to pick the next neighbor.

At each hop arrival at `receiver` (from `sender`):

1. **Increment hop count**, append receiver to `walk_nodes`.
2. **Loop-prevention drop**: if the walk returns to `src` after leaving, it is dropped.
3. **Observe link wait** on the traversed link $(sender,receiver)$ (this affects diagnostics; it does not itself decide acceptance).
4. **Acceptance decision**:
  - Acceptance is allowed only if `kMinTtl ≤ hops ≤ kMaxTtl` (defaults: 1..100).
  - The acceptance probability is `consume_probability(hops, kMaxTtl, buffered_keys[receiver][src], watermark_sz)`.
  Intuition: nodes that already have “enough” established keys for this source are less willing (or unwilling) to accept new scouts.

If not accepted and `hops < kMaxTtl`, the scout chooses the next neighbor via the RW token and continues.

### If accepted at node `tgt`

When a node accepts a scout:

1. Set `tgt = receiver`.
2. Compute `path = loop_erase_path(walk_nodes)` to obtain a simple path from `src` to `tgt`.
3. **Congestion drop rule (max per-link wait)**:
  - The target observes the waiting time on each hop of the *loop-erased path* at acceptance time $t$.
  - If **any** hop has observed wait $> 10\text{ s}$ (`kDropIfAnyLinkWaitGtS`), the scout is dropped (no reservations made).

### Return step (reservations)

If the scout passes the congestion check, the simulator performs a return phase over time:

- The return walks backward along the path from $(tgt \to src)$.
- The return walks backward along the path from $(tgt \to src)$.
- At each backward hop, it **enqueues one reservation** on that link queue and records the reservation’s `ready_time` for the corresponding *forward hop index*.
- The backward steps are separated by the same classical latency $\Delta = 5\text{ ms}$.

When the return reaches the source, the scout has produced per-hop ready times:

- `hop_ready_time[i]`: when the reserved key for hop $i$ (edge `path[i]→path[i+1]`) becomes available.

## Chunk transmission (fixed path, hop-by-hop timing)

After a scout returns to the source, the source schedules sending one **classical chunk** along the scout’s loop-erased path.

Key constraint: when the chunk reaches hop $i$’s sender node, the OTP material reserved for hop $i$ must already be ready.

Let:

- `send_time` be the time the chunk is injected at `src`.
- The chunk reaches node `path[i]` at `send_time + i·Δ` (because each hop adds fixed classical latency).
- The reserved key for hop $i$ becomes available at `hop_ready_time[i]`.

The source therefore chooses:

$$
sendtime = \max\Bigl(now,\ \max_i\bigl(hopreadytime[i] - i\cdot \Delta\bigr)\Bigr),
$$

so that for all hops $i$:

$$
sendtime + i\cdot \Delta \ge hopreadytime[i].
$$

Once started, the chunk traverses the fixed path with only classical latency per hop. When it reaches the target, the simulator records a `recv_chunk` event with the path.

## Blocks and key extraction (entropy-style accounting with cartel)

For each ordered pair $(src,tgt)$, the target groups arriving chunks into windows of size:

- `block_chunks` (default commonly 100 in experiments).

At block close, the simulator computes how many **extractable keys** the pair establishes from that block using a simplified “entropy-style” rule:

1. Consider the multiset of loop-erased paths observed in the block (one per chunk).
2. An adversary is a **cartel of size $m$** (`--cartel-size`):
  - $m=0$: no cartel (sees nothing).
  - $m=1$: one intermediate node chosen **optimally** to maximize how many of the block’s paths it appears on (excluding `src` and `tgt`).
  - $m=2$: two intermediate nodes chosen **optimally** to maximize coverage of paths by the OR of their appearances.
3. Let `max_seen` be the maximum number of block paths covered by the optimal cartel.
4. Define:

$$
h = \text{blockchunks} - maxseen.
$$

1. The number of extracted keys from the block is:

- `extracted_keys = min(max_block_keys, h)` if $h>0$, else 0.

This makes “every path goes through the same cartel node(s)” correspond to $maxseen = blockchunks$ and hence **zero** extracted keys.

### Buffered keys and willingness to accept scouts

The simulator maintains:

- `buffered_keys[tgt][src]`: accumulated extracted keys at `tgt` for `src`, used as a congestion/willingness signal for accepting scouts.
- `established_keys[tgt][src]`: accumulated extracted keys for reporting/stop condition (`--min-keys-per-pair`).

At each block close, `extracted_keys` is added to both.

## Output events

The program prints a header with run parameters and then a list of events:

- `recv_chunk time src tgt <path...>`: a chunk was delivered to `tgt`.
- `key_establ time src tgt key_count`: the block for $(src,tgt)$ closed at `time` and produced `key_count` extracted keys.

## `--verbose` diagnostics: what they mean

When `--verbose` is enabled, two kinds of diagnostics are printed to stderr.

### Periodic progress line

Every ~5 wall-clock seconds:

- Counts of processed events, queue size, chunks started/received.
- Scout totals: emitted, accepted.
- Scout drop breakdown (why a scout did not lead to a returning reservation):
  - `ttl1000`: exceeded an internal safety limit (walk too long).
  - `srcRet`: returned to source after leaving.
  - `maxTtl`: reached TTL limit without being accepted.
  - `wait`: accepted but dropped because some path hop had observed wait $>10\text{ s}$.
- Histogram `accept_hops[1..5,6+]`: hop-count depth at which scouts were accepted (after passing the wait check).

### Per-block line

At each block close for $(src,tgt)$, a `[block]` line includes:

- `uniq_paths`: number of distinct loop-erased paths seen in the block.
- `first_hops`: distribution of the first hop out of `src` across the block.
- `top_mid`: intermediate nodes ranked by how many block paths they appear on.
- `cartel_nodes`, `max_seen`, `h`, `keys`.
- Scout shape statistics over that block:
  - `accept_hops(min/avg/max)` and `hist[1..6+]`
  - `walk_v(min/avg/max)`: raw walk length in vertices when acceptance happened (includes loops).
  - `erased_v(min/avg/max)`: loop-erased path length in vertices (the actual chunk path).
- If `max_seen == block_chunks`, it prints `avoid_cartel_path`:
  - This is a **graph-level existence test**: whether there exists *some* `src→tgt` path in the current graph that avoids the chosen cartel nodes (it does **not** mean such a path was observed in the block).

## What is intentionally simplified

This simulator is a **model**, not a full QKD network stack. In particular:

- Link SKR is constant, and all key consumption is in fixed 256-bit chunks.
- Classical latency is constant per hop (5 ms).
- The accept probability depends on local buffered keys and hop count; it is not derived from a full protocol implementation.
- Security is reduced to “cartel covers these paths → those chunks are compromised”, producing the simple $h=\text{blockchunks}-maxseen$ accounting.

