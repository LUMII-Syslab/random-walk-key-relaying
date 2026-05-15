"""Suurballe's algorithm for K node-disjoint s-t paths.

The graph from `readgraphcsv.Graph` is undirected and unweighted, so every arc
has unit length and the "minimum total length" objective of Suurballe (1974)
reduces to "minimum total hop count".

Implementation follows the Suurballe-Tarjan formulation, equivalent to the
node-splitting / canonic-network reduction discussed in Sections 6 and 8 of
the paper:

  1. Encode node-disjointness by splitting each non-terminal v into v_in -> v_out
     with unit capacity. Terminals s, t get capacity K on their split arc.
  2. Each undirected edge {u, v} becomes two unit-capacity arcs of cost 1
     (u_out -> v_in and v_out -> u_in).
  3. Run Dijkstra K times on the residual graph, reweighting arc costs with
     node potentials (pot[v] += shortest-path distance from each iteration) so
     that residual reverse arcs - which carry negative cost - present
     non-negative reduced costs to Dijkstra. This is exactly the "canonic
     equivalent network" of Definition 6.
  4. Decompose the K-unit s -> t flow into K node-disjoint paths.

Reference:
    J. W. Suurballe, "Disjoint paths in a network", Networks 4 (1974), 125-145.
"""
from __future__ import annotations

import heapq

from readgraphcsv import Graph


def suurballe(graph: Graph, s: int, t: int, k: int) -> list[list[int]]:
    """Return ``k`` node-disjoint s-t paths with minimum total hop count.

    Each path is a list of node indices starting with ``s`` and ending with
    ``t``. Internal nodes are not shared between any two returned paths.

    Raises ``ValueError`` if ``s == t``, if the indices are out of range, if
    ``k`` is negative, or if the graph contains fewer than ``k`` node-disjoint
    s-t paths.
    """
    n = len(graph.adj_list)
    if not (0 <= s < n and 0 <= t < n):
        raise ValueError(f"terminal out of range: s={s}, t={t}, n={n}")
    if s == t:
        raise ValueError("s and t must differ")
    if k < 0:
        raise ValueError("k must be non-negative")
    if k == 0:
        return []

    # Node splitting: original node v -> (v_in, v_out) at ids (2v, 2v+1).
    N = 2 * n
    src = 2 * s          # s_in is the source
    snk = 2 * t + 1      # t_out is the sink

    # Residual graph as parallel arrays. Forward arc at index 2i, its reverse
    # twin at 2i+1 (toggle with `e ^ 1`). cap[e^1] equals the flow currently
    # carried by the forward arc e.
    head: list[int] = []
    cap: list[int] = []
    cost: list[int] = []
    adj: list[list[int]] = [[] for _ in range(N)]

    def add_arc(u: int, v: int, c: int, w: int) -> None:
        adj[u].append(len(head))
        head.append(v); cap.append(c); cost.append(w)
        adj[v].append(len(head))
        head.append(u); cap.append(0); cost.append(-w)

    # Node-split arcs. Terminals carry up to k units (all paths start at s and
    # end at t); every other node has unit capacity, enforcing node-disjointness.
    for v in range(n):
        if v == s or v == t:
            add_arc(2 * v, 2 * v + 1, k, 0)
        else:
            add_arc(2 * v, 2 * v + 1, 1, 0)

    # Edge arcs. Suppress arcs into s_in or out of t_out: they cannot occur on
    # any s -> t path and would only inflate the search.
    for u in range(n):
        for v in graph.adj_list[u]:
            if v <= u:
                continue
            if u != t and v != s:
                add_arc(2 * u + 1, 2 * v, 1, 1)
            if v != t and u != s:
                add_arc(2 * v + 1, 2 * u, 1, 1)

    # K shortest-augmenting-path iterations with Johnson-style potentials.
    # Initial costs are 0 or 1, so pot = 0 makes the first Dijkstra valid.
    INF = float("inf")
    pot = [0] * N

    for it in range(k):
        dist: list[float] = [INF] * N
        dist[src] = 0
        prev_edge: list[int] = [-1] * N
        pq: list[tuple[float, int]] = [(0, src)]
        while pq:
            d, u = heapq.heappop(pq)
            if d > dist[u]:
                continue
            for e in adj[u]:
                if cap[e] <= 0:
                    continue
                v = head[e]
                reduced = cost[e] + pot[u] - pot[v]
                # Invariant: every residual arc has non-negative reduced cost.
                # See Suurballe (1974), Section 9, induction proof.
                nd = d + reduced
                if nd < dist[v]:
                    dist[v] = nd
                    prev_edge[v] = e
                    heapq.heappush(pq, (nd, v))

        if dist[snk] == INF:
            raise ValueError(
                f"graph has only {it} node-disjoint s-t paths; {k} requested"
            )

        # Promote reduced-cost distances into the potential. Unreached nodes
        # are unreachable from src in the residual and stay so (the reachable
        # set is monotonically non-increasing across iterations), so their
        # potentials never get consulted again - leave them as-is.
        for v in range(N):
            if dist[v] < INF:
                pot[v] += int(dist[v])

        # Augment one unit of flow along the discovered shortest path.
        v = snk
        while v != src:
            e = prev_edge[v]
            cap[e] -= 1
            cap[e ^ 1] += 1
            v = head[e ^ 1]

    # Decompose the unit s -> t flow into k node-disjoint paths. Each path
    # alternates v_in (even id) -> v_out (odd id) -> next-node v_in. Recording
    # the node every time we land on an even id reconstructs the original path.
    paths: list[list[int]] = []
    for _ in range(k):
        path: list[int] = []
        u = src
        while u != snk:
            if u % 2 == 0:
                path.append(u // 2)
            chosen = -1
            for e in adj[u]:
                # Forward arcs sit at even indices; flow on them is cap[e^1].
                if (e & 1) == 0 and cap[e ^ 1] > 0:
                    chosen = e
                    break
            if chosen < 0:
                raise RuntimeError("flow decomposition failed (graph corrupted)")
            cap[chosen ^ 1] -= 1
            cap[chosen] += 1
            u = head[chosen]
        paths.append(path)

    return paths
