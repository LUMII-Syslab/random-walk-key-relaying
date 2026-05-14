from dataclasses import dataclass
from readgraphcsv import Graph, read_graph
from itertools import combinations
from collections import defaultdict
from rwvariants import random_walk
from tqdm import tqdm
from joblib import Memory, Parallel, delayed

memory = Memory('.cache', verbose=0)


@dataclass
class ExposureStats:
    one: dict[int, float]
    two: dict[tuple[int, int], float]
    three: dict[tuple[int, int, int], float]


@memory.cache
def compute_exposures(graph: Graph, s, t, variant: str = 'HS',
                      loop_erase: bool = True, runs: int = 10000) -> ExposureStats:
    one_hits: dict = defaultdict(int)
    two_hits: dict = defaultdict(int)
    three_hits: dict = defaultdict(int)

    for i in range(runs):
        path = random_walk(graph, s, t, variant, loop_erase=loop_erase, seed=i)
        visited = sorted(set(path))
        for u in visited:
            one_hits[u] += 1
        for u, v in combinations(visited, 2):
            two_hits[(u, v)] += 1
        for u, v, w in combinations(visited, 3):
            three_hits[(u, v, w)] += 1

    return ExposureStats(
        one={u: one_hits[u] / runs for u in one_hits},
        two={(u, v): two_hits[(u, v)] / runs for u, v in two_hits},
        three={(u, v, w): three_hits[(u, v, w)] / runs for u, v, w in three_hits},
    )


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

    max_prob = 0.0
    max_st = max_uvw = None
    for (s, t), stats in all_exposures.items():
        if not stats.three:
            continue
        uvw = max(stats.three, key=stats.three.__getitem__)
        if stats.three[uvw] > max_prob:
            max_prob = stats.three[uvw]
            max_st, max_uvw = (s, t), uvw

    names = geant.node_names or []
    def name(i): return names[i] if names else i
    print(f'Max 3-node exposure: {max_prob:.4f} for ({name(max_st[0])},{name(max_st[1])}) via {tuple(name(i) for i in max_uvw)}')
