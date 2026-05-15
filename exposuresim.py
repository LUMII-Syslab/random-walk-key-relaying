"""Run with: `python exposuresim.py [nsfnet|geant|generated|generated:N ...]`.

For each graph (default: all three), prints rows of `tab:protection-set-comparison`
plus an adaptive-MP-2 column and per-row cartel/pair counts. Uses HS with
loop-erasure, M=1024, tau=95%, Suurballe k=min(2,kappa(s,t)) for static MP.

Memory note: we never hold the full per-pair `three[u,v,w]` cube in memory;
each pair is reduced to a packed boolean tensor (one / two / three > tau).
For n=99 that is ~125 KB per (s,t), total ~1.2 GB across all ordered pairs."""
import argparse
import sys
from dataclasses import dataclass
from itertools import combinations
from readgraphcsv import Graph, read_graph, synthetic_graph_snapshot
from rwvariants import random_walk
from tqdm import tqdm
from joblib import Memory, Parallel, delayed
from numba import njit
import networkx as nx
import numpy as np

from suurballe import suurballe

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


def compute_thresholded(graph: Graph, s, t, tau: float,
                        variant: str = 'HS', loop_erase: bool = True,
                        runs: int = 10000):
    """Wraps `compute_exposures` (which is cached) and thresholds at `tau`.
    Not cached itself: thresholding is cheap, and a second cache would only
    duplicate the underlying `compute_exposures` cache.

    Returns: (one_aff[n] bool, two_aff[n,n] bool, three_packed[ceil(n^3/8)] uint8)."""
    stats = compute_exposures(graph, s, t, variant, loop_erase, runs)
    one_aff = stats.one > tau
    two_aff = stats.two > tau
    three_packed = np.packbits((stats.three > tau).ravel(), bitorder='little')
    return one_aff, two_aff, three_packed


def build_thresholded_arrays(graph: Graph, tau: float,
                             variant: str = 'HS', loop_erase: bool = True,
                             runs: int = 10000):
    """For all ordered (s,t), compute packed boolean exposure tensors.

    Memory: O(n_pairs * n^3 / 8) bytes. For Generated (n=99) that's ~1.2 GB."""
    n = len(graph.adj_list)
    ordered = [(s, t) for s in range(n) for t in range(n) if s != t]
    n_pairs = len(ordered)
    pair_id = {st: i for i, st in enumerate(ordered)}

    one_all = np.zeros((n_pairs, n), dtype=bool)
    two_all = np.zeros((n_pairs, n, n), dtype=bool)
    n3_packed_size = (n * n * n + 7) // 8
    three_packed = np.zeros((n_pairs, n3_packed_size), dtype=np.uint8)

    def _proc(s, t):
        oa, ta, tp = compute_thresholded(graph, s, t, tau, variant,
                                         loop_erase, runs)
        return s, t, oa, ta, tp

    print(f'  building thresholded arrays for {n_pairs} pairs '
          f'(~{(n_pairs * n3_packed_size) / 1e9:.2f} GB packed)...')
    # Processes: joblib cache persistence (pickle.dump) holds the GIL and
    # dominates per-call cost when the work itself is short (~0.5 s of numba
    # aggregation per pair on n=99). Threads only get ~4x speedup; processes
    # get close to nproc x. Concurrent reads/writes on Memory are safe.
    parallel = Parallel(n_jobs=-1, return_as='generator_unordered')
    for s, t, oa, ta, tp in tqdm(
        parallel(delayed(_proc)(s, t) for s, t in ordered),
        total=n_pairs, desc='exposures', mininterval=5.0,
    ):
        pid = pair_id[(s, t)]
        one_all[pid] = oa
        two_all[pid] = ta
        three_packed[pid] = tp
    return ordered, pair_id, one_all, two_all, three_packed


def get_eligible_st_pairs(graph_nx: nx.Graph,
                          cartel: tuple[int, ...]) -> list[tuple[int, int]]:
    """Ordered (s,t) pairs with s,t not in cartel and connected in G[V\\C]."""
    cartel_set = set(cartel)
    keep = [v for v in graph_nx.nodes if v not in cartel_set]
    subg = graph_nx.subgraph(keep)
    pairs: list[tuple[int, int]] = []
    for component in nx.connected_components(subg):
        comp = list(component)
        for i, s in enumerate(comp):
            for j, t in enumerate(comp):
                if i != j:
                    pairs.append((s, t))
    return pairs


def adaptive_mp2_mask(graph_nx: nx.Graph,
                      cartel: tuple[int, ...],
                      pairs: list[tuple[int, int]]) -> np.ndarray:
    """For each (s,t), True iff kappa(G[V\\C])(s,t) >= 2.

    Equivalent to: s and t lie in the same biconnected component of size>=3
    in G[V\\C]. Used as the protection set of an adaptive MP-2 baseline that
    re-picks two disjoint paths after the cartel is revealed."""
    cartel_set = set(cartel)
    subg = graph_nx.subgraph([v for v in graph_nx.nodes if v not in cartel_set])
    node_bcc_ids: dict[int, set[int]] = {v: set() for v in subg.nodes}
    for bid, bcc in enumerate(nx.biconnected_components(subg)):
        if len(bcc) >= 3:
            for v in bcc:
                node_bcc_ids[v].add(bid)
    return np.array([
        not node_bcc_ids[s].isdisjoint(node_bcc_ids[t])
        for s, t in pairs
    ])


def _rf_affected_mask(cartel: tuple[int, ...], pair_idx: np.ndarray,
                      n: int, one_all, two_all, three_packed) -> np.ndarray:
    """For each pair in `pair_idx`, return whether p_C^{(s,t)} > tau."""
    m = len(cartel)
    if m == 1:
        return one_all[pair_idx, cartel[0]]
    if m == 2:
        u, v = cartel
        return two_all[pair_idx, u, v]
    if m == 3:
        u, v, w = cartel
        flat = u * n * n + v * n + w
        byte_idx = flat >> 3
        bit_idx = flat & 7
        return ((three_packed[pair_idx, byte_idx] >> bit_idx) & 1).astype(bool)
    raise ValueError(f'cartel size must be 1, 2, or 3, got {m}')


def compute_protection_table(
    graph: Graph,
    cartel_size: int,
    ordered: list[tuple[int, int]],
    pair_id: dict[tuple[int, int], int],
    one_all: np.ndarray,
    two_all: np.ndarray,
    three_packed: np.ndarray,
    st_path_sets: dict[tuple[int, int], list[frozenset]],
) -> dict:
    """Compute one row of `tab:protection-set-comparison` for cartel size m.

    Returns averages of pi_RF, pi_MP-static, pi_RF\\MP, pi_MP\\RF, pi_aMP-2 over
    eligible unordered cartels, plus context counts."""
    n = len(graph.adj_list)
    g_nx = graph.to_nx()

    cartels = list(combinations(range(n), cartel_size))
    sums = np.zeros(5)  # rf, mp, rf\mp, mp\rf, amp2
    n_eligible_cartels = 0
    total_eligible_pairs = 0
    for cartel in tqdm(cartels, desc=f'  m={cartel_size}'):
        pairs = get_eligible_st_pairs(g_nx, cartel)
        if not pairs:
            continue
        cartel_set = frozenset(cartel)
        n_pairs = len(pairs)
        pair_idx = np.fromiter((pair_id[p] for p in pairs), dtype=np.int32,
                               count=n_pairs)

        affected = _rf_affected_mask(cartel, pair_idx, n,
                                     one_all, two_all, three_packed)
        rf_mask = ~affected
        mp_mask = np.fromiter(
            (any(cartel_set.isdisjoint(P) for P in st_path_sets[p])
             for p in pairs),
            dtype=bool, count=n_pairs,
        )
        amp2_mask = adaptive_mp2_mask(g_nx, cartel, pairs)

        rf = int(rf_mask.sum())
        mp = int(mp_mask.sum())
        both = int((rf_mask & mp_mask).sum())
        amp2 = int(amp2_mask.sum())

        sums += np.array([rf, mp, rf - both, mp - both, amp2]) / n_pairs
        n_eligible_cartels += 1
        total_eligible_pairs += n_pairs

    means = sums / max(n_eligible_cartels, 1)
    return {
        'm':                  cartel_size,
        'pi_rf':              float(means[0]),
        'pi_mp':              float(means[1]),
        'pi_rf_minus_mp':     float(means[2]),
        'pi_mp_minus_rf':     float(means[3]),
        'pi_amp2':            float(means[4]),
        'total_cartels':      len(cartels),
        'eligible_cartels':   n_eligible_cartels,
        'total_eligible_st':  total_eligible_pairs,
    }


def load_graph(name: str) -> tuple[str, Graph]:
    """``nsfnet`` | ``geant`` | ``generated`` | ``generated:N``"""
    if name in ('nsfnet', 'geant', 'secoqc'):
        return name.upper(), read_graph(name)
    if name.startswith('generated'):
        _, _, n_str = name.partition(':')
        n = int(n_str) if n_str else 99
        return f'Generated({n})', synthetic_graph_snapshot(n)
    raise ValueError(f'unknown graph: {name}')


def run_for_graph(label: str, graph: Graph, tau: float,
                  sizes: list[int]) -> list[dict]:
    g_nx = graph.to_nx()
    n = len(graph.adj_list)
    ordered = [(s, t) for s in range(n) for t in range(n) if s != t]

    print(f'\n=== {label}  n={n}  e={g_nx.number_of_edges()} ===')

    ordered, pair_id, one_all, two_all, three_packed = \
        build_thresholded_arrays(graph, tau)

    print('  computing s-t node connectivity...')
    st_kappa = {st: nx.node_connectivity(g_nx, *st)
                for st in tqdm(ordered, desc='kappa')}

    print('  computing Suurballe paths with k=min(2, kappa)...')
    st_path_sets: dict[tuple[int, int], list[frozenset]] = {}
    for st in tqdm(ordered, desc='suurballe'):
        k = min(2, st_kappa[st])
        paths = suurballe(graph, st[0], st[1], k) if k > 0 else []
        st_path_sets[st] = [frozenset(p) for p in paths]

    rows: list[dict] = []
    for m in sizes:
        row = compute_protection_table(graph, m, ordered, pair_id,
                                       one_all, two_all, three_packed,
                                       st_path_sets)
        rows.append(row)
        print(f'  m={m}  pi_RF={row["pi_rf"]*100:6.2f}%  '
              f'pi_MP={row["pi_mp"]*100:6.2f}%  '
              f'pi_RF\\MP={row["pi_rf_minus_mp"]*100:6.2f}%  '
              f'pi_MP\\RF={row["pi_mp_minus_rf"]*100:6.2f}%  '
              f'pi_aMP2={row["pi_amp2"]*100:6.2f}%  '
              f'#eligible/#total={row["eligible_cartels"]}/{row["total_cartels"]}  '
              f'sum|E(C)|={row["total_eligible_st"]}')
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('graphs', nargs='*',
                        default=['nsfnet', 'geant', 'generated'],
                        help='graph names; use generated:N for synthetic snapshot')
    parser.add_argument('--tau', type=float, default=0.95)
    parser.add_argument('--sizes', type=int, nargs='+', default=[1, 2, 3])
    args = parser.parse_args()

    all_rows: dict[str, list[dict]] = {}
    for name in args.graphs:
        label, graph = load_graph(name)
        all_rows[label] = run_for_graph(label, graph, args.tau, args.sizes)

    print('\n=== latex rows (tab:protection-set-comparison + adaptive MP-2) ===',
          file=sys.stderr)
    print('Graph & m & pi_RF & pi_MP & pi_RF\\MP & pi_MP\\RF & pi_aMP2 & '
          'eligible_cartels/total & sum|E(C)|', file=sys.stderr)
    for label, rows in all_rows.items():
        for row in rows:
            print(f'{label} & {row["m"]} & '
                  f'{row["pi_rf"]*100:.2f}\\% & '
                  f'{row["pi_mp"]*100:.2f}\\% & '
                  f'{row["pi_rf_minus_mp"]*100:.2f}\\% & '
                  f'{row["pi_mp_minus_rf"]*100:.2f}\\% & '
                  f'{row["pi_amp2"]*100:.2f}\\% & '
                  f'{row["eligible_cartels"]}/{row["total_cartels"]} & '
                  f'{row["total_eligible_st"]}'
                  f' \\\\', file=sys.stderr)
