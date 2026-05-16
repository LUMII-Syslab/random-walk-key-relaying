"""Rank 3-node cartels on NSFNET by the RF-vs-MP protection contrast.

For each unordered cartel C of size 3, compute over its eligible ordered pairs
E(C) = {(s,t) : s,t notin C, s and t connected in G[V\\C]}:

    pi_RF      = |{(s,t) in E(C) : p_C^{(s,t)} <= tau}|     / |E(C)|
    pi_MP      = |{(s,t) in E(C) : exists Suurballe path disjoint from C}| / |E(C)|
    pi_RF\\MP  = |Pi_RF \\ Pi_MP| / |E(C)|
    pi_MP\\RF  = |Pi_MP \\ Pi_RF| / |E(C)|

The MP baseline is the same static one used in `tab:protection-set-comparison`:
Suurballe with k = kappa(s,t) on the FULL graph (paths fixed before C revealed).

The script prints the cartels with the largest pi_RF\\MP (RF protects, MP fails)
and also reports the cartel-wide pi_RF, pi_MP, eligibility count, and the list
of (s,t) pairs in Pi_RF\\Pi_MP for the very top cartel.

Defaults mirror `exposuresim.py`: HS + loop-erasure, M=runs=10000, tau=0.95.
Caching from `compute_exposures` is reused, so re-running is cheap once warm.
"""
from __future__ import annotations

import argparse
from itertools import combinations

import networkx as nx
import numpy as np
from tqdm import tqdm

from exposuresim import (
    _rf_affected_mask,
    build_thresholded_arrays,
    get_eligible_st_pairs,
)
from readgraphcsv import read_graph
from suurballe import suurballe


def labels_of(graph, cartel):
    if graph.node_names is None:
        return tuple(str(v) for v in cartel)
    return tuple(str(graph.node_names[v]) for v in cartel)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--tau', type=float, default=0.95)
    parser.add_argument('--runs', type=int, default=10000,
                        help='walks per ordered pair (matches exposuresim default)')
    parser.add_argument('--variant', default='HS')
    parser.add_argument('--no-loop-erase', action='store_true')
    parser.add_argument('--top', type=int, default=10,
                        help='how many top cartels to print')
    parser.add_argument('--sort', choices=['frac', 'count'], default='frac',
                        help='rank by pi_RF\\MP fraction or by absolute pair count')
    args = parser.parse_args()

    graph = read_graph('nsfnet')
    g_nx = graph.to_nx()
    n = len(graph.adj_list)
    loop_erase = not args.no_loop_erase

    print(f'NSFNET: n={n}, e={g_nx.number_of_edges()}, '
          f'variant={args.variant} (loop_erase={loop_erase}), '
          f'tau={args.tau}, runs={args.runs}')

    ordered, pair_id, one_all, two_all, three_packed = build_thresholded_arrays(
        graph, args.tau, args.variant, loop_erase, args.runs,
    )

    print('  computing s-t node connectivity (full graph)...')
    st_kappa = {st: nx.node_connectivity(g_nx, *st)
                for st in tqdm(ordered, desc='kappa', mininterval=1.0)}

    print('  computing Suurballe paths with k=kappa(s,t)...')
    st_path_sets: dict[tuple[int, int], list[frozenset]] = {}
    for st in tqdm(ordered, desc='suurballe', mininterval=1.0):
        k = st_kappa[st]
        paths = suurballe(graph, st[0], st[1], k) if k > 0 else []
        st_path_sets[st] = [frozenset(p) for p in paths]

    cartels = list(combinations(range(n), 3))
    rows = []
    for cartel in tqdm(cartels, desc='cartels', mininterval=1.0):
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
        rf = int(rf_mask.sum())
        mp = int(mp_mask.sum())
        both = int((rf_mask & mp_mask).sum())
        rf_only = rf - both
        mp_only = mp - both
        rows.append({
            'cartel':       cartel,
            'n_pairs':      n_pairs,
            'rf':           rf,
            'mp':           mp,
            'rf_only':      rf_only,
            'mp_only':      mp_only,
            'pi_rf':        rf / n_pairs,
            'pi_mp':        mp / n_pairs,
            'pi_rf_only':   rf_only / n_pairs,
            'pi_mp_only':   mp_only / n_pairs,
            'rf_only_pairs': [p for p, m in zip(pairs, rf_mask & ~mp_mask) if m],
        })

    if not rows:
        print('no eligible 3-cartels')
        return

    key = (lambda r: (r['pi_rf_only'], r['rf_only'])) if args.sort == 'frac' \
        else (lambda r: (r['rf_only'], r['pi_rf_only']))
    rows.sort(key=key, reverse=True)

    print(f'\nTop {args.top} 3-cartels by pi_RF\\MP '
          f'({"fraction" if args.sort == "frac" else "absolute count"}):')
    print('rank  cartel              |E(C)|  pi_RF    pi_MP    pi_RF\\MP   pi_MP\\RF   '
          'RF_only / |E(C)|')
    for rank, row in enumerate(rows[:args.top], 1):
        labels = labels_of(graph, row['cartel'])
        labels_str = '{' + ','.join(labels) + '}'
        print(f'{rank:4d}  {labels_str:<18}  {row["n_pairs"]:5d}  '
              f'{row["pi_rf"]*100:6.2f}%  {row["pi_mp"]*100:6.2f}%  '
              f'{row["pi_rf_only"]*100:8.2f}%  {row["pi_mp_only"]*100:7.2f}%  '
              f'{row["rf_only"]:3d} / {row["n_pairs"]:3d}')

    best = rows[0]
    best_labels = labels_of(graph, best['cartel'])
    print(f'\nBest cartel: {{{",".join(best_labels)}}}  '
          f'(indices {best["cartel"]})')
    print(f'  |E(C)|        = {best["n_pairs"]}  (ordered)')
    print(f'  pi_RF         = {best["pi_rf"]*100:6.2f}%')
    print(f'  pi_MP         = {best["pi_mp"]*100:6.2f}%')
    print(f'  pi_RF\\MP      = {best["pi_rf_only"]*100:6.2f}%  '
          f'({best["rf_only"]} pairs)')
    print(f'  pi_MP\\RF      = {best["pi_mp_only"]*100:6.2f}%  '
          f'({best["mp_only"]} pairs)')
    print('  pairs (s,t) in Pi_RF \\ Pi_MP:')
    for s, t in best['rf_only_pairs']:
        s_lbl = graph.node_names[s] if graph.node_names else s
        t_lbl = graph.node_names[t] if graph.node_names else t
        kappa = st_kappa[(s, t)]
        paths = st_path_sets[(s, t)]
        path_lbls = [
            '['
            + '->'.join(
                str(graph.node_names[v]) if graph.node_names else str(v)
                for v in suurballe(graph, s, t, kappa)[i]
            )
            + ']'
            for i in range(len(paths))
        ]
        print(f'    {s_lbl}->{t_lbl}  kappa={kappa}  MP paths={path_lbls}')


if __name__ == '__main__':
    main()
