from dataclasses import dataclass
from itertools import combinations
from readgraphcsv import Graph, read_graph
from rwvariants import random_walk
from tqdm import tqdm
from joblib import Memory, Parallel, delayed
from numba import njit
import networkx as nx
import numpy as np

memory = Memory('.cache', verbose=0)


@dataclass
class ExposureStats:
    """Union-exposure probabilities. ``two`` is filled only for ``u < v`` and
    ``three`` only for ``u < v < w``; other entries are zero."""
    one: np.ndarray
    two: np.ndarray
    three: np.ndarray


@njit(cache=True)
def _aggregate_hits(visited: np.ndarray, runs: int, n: int):
    # cs[u]      = #runs with u in path
    # pi[u, v]   = #runs with both u and v in path     (u < v)
    # ti[u,v,w]  = #runs with all of u, v, w in path   (u < v < w)
    cs = np.zeros(n, dtype=np.int64)
    pi = np.zeros((n, n), dtype=np.int64)
    ti = np.zeros((n, n, n), dtype=np.int64)
    bits = np.empty(n, dtype=np.int64)
    for r in range(runs):
        k = 0
        for u in range(n):
            if visited[r, u]:
                bits[k] = u
                k += 1
                cs[u] += 1
        for i in range(k):
            bi = bits[i]
            for j in range(i + 1, k):
                bj = bits[j]
                pi[bi, bj] += 1
                for l in range(j + 1, k):
                    ti[bi, bj, bits[l]] += 1

    inv = 1.0 / runs
    one = cs.astype(np.float64) * inv
    two = np.zeros((n, n), dtype=np.float64)
    three = np.zeros((n, n, n), dtype=np.float64)
    for u in range(n):
        cu = cs[u]
        for v in range(u + 1, n):
            cv = cs[v]
            puv = pi[u, v]
            two[u, v] = (cu + cv - puv) * inv
            for w in range(v + 1, n):
                three[u, v, w] = (
                    cu + cv + cs[w]
                    - puv - pi[u, w] - pi[v, w]
                    + ti[u, v, w]
                ) * inv
    return one, two, three


@memory.cache
def compute_exposures(graph: Graph, s, t, variant: str = 'HS',
                      loop_erase: bool = True, runs: int = 10000) -> ExposureStats:
    n = len(graph.adj_list)
    visited = np.zeros((runs, n), dtype=np.bool_)
    for i in range(runs):
        path = random_walk(graph, s, t, variant, loop_erase=loop_erase, seed=i)
        visited[i, np.asarray(path, dtype=np.int64)] = True
    one, two, three = _aggregate_hits(visited, runs, n)
    return ExposureStats(one=one, two=two, three=three)


@memory.cache
def get_eligible_sets(graph: Graph, s: int, t: int, mx_size: int = 3) -> list[tuple[int, ...]]:
    # a set is eligible if it does not contain s or t nor does its removal disconnect s from t
    n = len(graph.adj_list)
    g_nx = graph.to_nx()
    all_nodes = set(range(n))
    eligible_sets: list[tuple[int, ...]] = []
    for size in range(1, mx_size + 1):
        for removed in combinations(range(n), size):
            if s in removed or t in removed:
                continue
            subg = g_nx.subgraph(all_nodes - set(removed))
            if not nx.has_path(subg, s, t):
                continue
            eligible_sets.append(removed)
    return eligible_sets

if __name__ == '__main__':
    geant = read_graph('geant')
    n = len(geant.adj_list)
    idx_pairs = list(combinations(range(n), 2))

    all_exposures: dict[tuple, ExposureStats] = dict(zip(
        idx_pairs,
        Parallel(n_jobs=-1, prefer='threads')(
            delayed(compute_exposures)(geant, s, t)
            for s, t in tqdm(idx_pairs, desc='Computing exposures')
        )
    ))

    eligible_three: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
    for s, t in tqdm(idx_pairs, desc='Computing eligible sets'):
        eligible_three[(s, t)] = [
            tup for tup in get_eligible_sets(geant, s, t) if len(tup) == 3
        ]

    max_prob = 0.0
    max_st = max_uvw = None
    for (s, t), stats in tqdm(all_exposures.items(), desc='Computing max 3-node exposure'):
        for uvw in eligible_three.get((s, t), ()):
            prob = float(stats.three[uvw])
            if prob > max_prob:
                max_prob = prob
                max_st, max_uvw = (s, t), uvw

    names = geant.node_names or []
    def name(i): return names[i] if names else i
    print(f'Max 3-node exposure: {max_prob:.4f} for ({name(max_st[0])},{name(max_st[1])}) via {tuple(name(i) for i in max_uvw)}')
