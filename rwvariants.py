from typing import Literal
from numba import njit
from numba.typed import List as NumbaList
from readgraphcsv import Graph, read_graph
import numpy as np


@njit(cache=True)
def _has_neighbor(nbrs: np.ndarray, node: int) -> bool:
    for n in nbrs:
        if n == node:
            return True
    return False


@njit(cache=True)
def _hs_node_score(node_idx: int, walk_seed: int) -> np.uint64:
    # splitmix64-style hash; deterministic per (node, seed), not matching C++ seed_seq
    x = np.uint64(node_idx) * np.uint64(0x9e3779b97f4a7c15) ^ np.uint64(walk_seed) * np.uint64(0x6c62272e07bb0142)
    x ^= x >> np.uint64(30)
    x *= np.uint64(0xbf58476d1ce4e5b9)
    x ^= x >> np.uint64(27)
    x *= np.uint64(0x94d049bb133111eb)
    x ^= x >> np.uint64(31)
    return x


@njit(cache=True)
def _rw_R(graph: NumbaList, s: int, t: int, seed: int) -> np.ndarray:
    np.random.seed(seed)
    pos = s
    path = [pos]
    while pos != t:
        nbrs = graph[pos]
        if _has_neighbor(nbrs, t):
            pos = t
        else:
            pos = np.random.choice(nbrs)
        path.append(pos)
    return np.array(path)


@njit(cache=True)
def _rw_NB(graph: NumbaList, s: int, t: int, seed: int) -> np.ndarray:
    np.random.seed(seed)
    pos = s
    previous = -1
    path = [pos]
    while pos != t:
        nbrs = graph[pos]
        if _has_neighbor(nbrs, t):
            previous = pos
            pos = t
        elif len(nbrs) == 1:
            previous = pos
            pos = nbrs[0]
        else:
            choices = [n for n in nbrs if n != previous]
            previous = pos
            pos = np.random.choice(np.array(choices))
        path.append(pos)
    return np.array(path)


@njit(cache=True)
def _rw_LRV(graph: NumbaList, s: int, t: int, seed: int) -> np.ndarray:
    np.random.seed(seed)
    pos = s
    age = 0
    last_seen = {s: 0}
    path = [pos]
    while pos != t:
        nbrs = graph[pos]
        if _has_neighbor(nbrs, t):
            age += 1
            last_seen[t] = age
            pos = t
        elif len(nbrs) == 1:
            chosen = nbrs[0]
            age += 1
            last_seen[chosen] = age
            pos = chosen
        else:
            min_time = age + 1
            for n in nbrs:
                t_n = last_seen[n] if n in last_seen else -1
                if t_n < min_time:
                    min_time = t_n
            choices = [n for n in nbrs if (last_seen[n] if n in last_seen else -1) == min_time]
            chosen = np.random.choice(np.array(choices))
            age += 1
            last_seen[chosen] = age
            pos = chosen
        path.append(pos)
    return np.array(path)


@njit(cache=True)
def _rw_HS(graph: NumbaList, s: int, t: int, seed: int) -> np.ndarray:
    np.random.seed(seed)
    pos = s
    age = 0
    visited = set()
    visited.add(s)
    path = [pos]
    while pos != t:
        nbrs = graph[pos]
        if _has_neighbor(nbrs, t):
            visited.add(t)
            age += 1
            pos = t
        elif len(nbrs) == 1:
            chosen = nbrs[0]
            visited.add(chosen)
            age += 1
            pos = chosen
        else:
            candidates = [n for n in nbrs if n not in visited]
            if len(candidates) == 0:
                candidates = [n for n in nbrs]
            max_score = np.uint64(0)
            choices = [candidates[0]]
            choices.clear()
            for n in candidates:
                score = _hs_node_score(n, seed) if n not in visited else np.uint64(0)
                if score > max_score:
                    max_score = score
                    choices.clear()
                    choices.append(n)
                elif score == max_score:
                    choices.append(n)
            chosen = np.random.choice(np.array(choices))
            visited.add(chosen)
            age += 1
            pos = chosen
        path.append(pos)
    return np.array(path)


def _loop_erase(path: np.ndarray) -> np.ndarray:
    result = []
    seen: dict[int, int] = {}
    for node in path:
        node = int(node)
        if node in seen:
            idx = seen[node]
            for evicted in result[idx + 1:]:
                del seen[evicted]
            del result[idx + 1:]
        else:
            seen[node] = len(result)
            result.append(node)
    return np.array(result, dtype=np.int64)


def _single_walk(graph: NumbaList, s: int, t: int, rw_variant: str, seed: int) -> np.ndarray:
    if rw_variant == 'R':
        path = _rw_R(graph, s, t, seed)
    elif rw_variant == 'NB':
        path = _rw_NB(graph, s, t, seed)
    elif rw_variant == 'LRV':
        path = _rw_LRV(graph, s, t, seed)
    elif rw_variant == 'HS':
        path = _rw_HS(graph, s, t, seed)
    else:
        raise ValueError(f"Unknown variant: {rw_variant}")
    return path


def _numba_adj(graph: Graph) -> NumbaList:
    if 'numba_adj' not in graph._cache:
        nl: NumbaList = NumbaList()
        for nbrs in graph.adj_list:
            nl.append(np.array(nbrs, dtype=np.int64))
        graph._cache['numba_adj'] = nl
    return graph._cache['numba_adj']



def random_walk(graph: Graph, s: int, t: int,
                rw_variant: Literal['R', 'NB', 'LRV', 'HS'],
                loop_erase: bool = False, seed: int = 0) -> list[int]:
    path = _single_walk(_numba_adj(graph), s, t, rw_variant, seed)
    if loop_erase:
        path = _loop_erase(path)
    return path.tolist()


if __name__ == '__main__':
    geant = read_graph('geant')
    for variant in ('R', 'NB', 'LRV', 'HS'):
        single = random_walk(geant, 0, 1, variant)
        erased = random_walk(geant, 0, 1, variant, loop_erase=True)
        print(variant, 'raw:', single, 'erased:', erased)
