from __future__ import annotations

from helpers.utils import synthetic_graph_snapshot


def main() -> None:
    graph = synthetic_graph_snapshot(99)
    total_distance = 0
    pair_count = 0

    for src, distances in graph_shortest_path_lengths(graph).items():
        for tgt, distance in distances.items():
            if src == tgt:
                continue
            total_distance += distance
            pair_count += 1

    average_distance = total_distance / pair_count
    print(f"nodes={graph.number_of_nodes()} ordered_pairs={pair_count}")
    print(f"average_shortest_path_length={average_distance:.6f}")


def graph_shortest_path_lengths(graph):
    return dict(__import__("networkx").all_pairs_shortest_path_length(graph))


if __name__ == "__main__":
    main()
