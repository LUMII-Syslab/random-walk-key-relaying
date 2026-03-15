from __future__ import annotations

import networkx as nx

from helpers.utils import synthetic_graph_snapshot


def main() -> None:
    graph = synthetic_graph_snapshot(99)
    total_shortest_distance = 0
    total_second_distance = 0
    total_average_distance = 0.0
    pair_count = 0
    pair_count_with_second_path = 0

    for src in graph.nodes:
        for tgt in graph.nodes:
            if src == tgt:
                continue

            shortest_path = nx.shortest_path(graph, src, tgt)
            shortest_distance = len(shortest_path) - 1
            second_distance = second_path_length_without_shortest_nodes(graph, shortest_path)

            total_shortest_distance += shortest_distance
            pair_count += 1

            if second_distance is None:
                continue

            total_second_distance += second_distance
            total_average_distance += (shortest_distance + second_distance) / 2
            pair_count_with_second_path += 1

    average_shortest_distance = total_shortest_distance / pair_count
    average_second_distance = total_second_distance / pair_count_with_second_path
    average_shortest_and_second_distance = total_average_distance / pair_count_with_second_path

    print(f"nodes={graph.number_of_nodes()} ordered_pairs={pair_count}")
    print(f"average_shortest_path_length={average_shortest_distance:.6f}")
    print(f"ordered_pairs_with_second_path={pair_count_with_second_path}")
    print(f"average_second_path_length={average_second_distance:.6f}")
    print(
        "average_shortest_and_second_path_length="
        f"{average_shortest_and_second_distance:.6f}"
    )


def second_path_length_without_shortest_nodes(
    graph: nx.Graph, shortest_path: list[int]
) -> int | None:
    # Keep endpoints so we can look for a node-disjoint alternative route.
    trimmed_graph = graph.copy()
    trimmed_graph.remove_nodes_from(shortest_path[1:-1])

    try:
        return nx.shortest_path_length(trimmed_graph, shortest_path[0], shortest_path[-1])
    except nx.NetworkXNoPath:
        return None


if __name__ == "__main__":
    main()
