from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd

from graphs import get_graph_nx_graph

KEYS_RE = re.compile(
    r"^keys\s+"
    r"(?P<keys>\d+)\s+"
    r"(?P<src>\S+)\s+"
    r"(?P<tgt>\S+)\s+"
    r"(?P<cartel>\S+)\s+"
    r"(?P<max_seen>\d+)"
)

HALT_RE = re.compile(r"^Halted at\s+(?P<time_s>[0-9]*\.?[0-9]+)\s+seconds\s*$")
SRC_RE = re.compile(r"^src_nodes:\s*(?P<srcs>.*)\s*$")
CONTEXT_SRC_RE = re.compile(r"--src-nodes=(?P<srcs>[^\s]+)")
CONTEXT_GRAPH_RE = re.compile(r"(?:-g=|--graph=)(?P<graph>\w+)")


@dataclass(frozen=True)
class KeyEvent:
    idx: int
    src: str
    tgt: str
    keys: int


def parse_scouted_log(path: Path) -> tuple[str, list[KeyEvent], float | None, str]:
    src_node: str | None = None
    graph_name = "GEANT"
    events: list[KeyEvent] = []
    halt_time_s: float | None = None

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            m = CONTEXT_GRAPH_RE.search(line)
            if m:
                graph_name = m.group("graph").upper()
                continue

            m = SRC_RE.match(line)
            if m:
                srcs = [s for s in m.group("srcs").split(",") if s]
                if len(srcs) == 1:
                    src_node = srcs[0]
                continue

            m = CONTEXT_SRC_RE.search(line)
            if m and src_node is None:
                srcs = [s for s in m.group("srcs").split(",") if s]
                if len(srcs) == 1:
                    src_node = srcs[0]
                continue

            m = HALT_RE.match(line)
            if m:
                halt_time_s = float(m.group("time_s"))
                continue

            m = KEYS_RE.match(line)
            if not m:
                continue

            keys = int(m.group("keys"))
            src = m.group("src")
            tgt = m.group("tgt")
            events.append(KeyEvent(idx=len(events), src=src, tgt=tgt, keys=keys))

    if src_node is None:
        if events:
            src_node = events[0].src
        else:
            raise ValueError(f"No src_nodes line and no key events found in {path}")

    return src_node, events, halt_time_s, graph_name


def make_time_axis(events: list[KeyEvent], halt_time_s: float | None) -> list[float]:
    if not events:
        return []
    if halt_time_s is None or halt_time_s <= 0:
        return [float(e.idx) for e in events]
    if len(events) == 1:
        return [0.0]
    return [halt_time_s * (e.idx / (len(events) - 1)) for e in events]


def apply_time_ticks_5m(ax: plt.Axes, halt_time_s: float | None) -> None:
    if halt_time_s is None:
        ax.set_xlabel("Event index (no timestamps in log)")
        return

    ax.set_xlabel("Time since cold start [minutes]")

    total_s = max(0.0, float(halt_time_s))
    step_s = 5 * 60
    ticks: list[float] = []
    x = 0.0
    while x <= total_s + 1e-9:
        ticks.append(float(x))
        x += step_s
    if not ticks:
        ticks = [0.0]

    def fmt_tick(sec: float) -> str:
        minutes = int(round(max(0.0, float(sec)) / 60.0))
        return str(minutes)

    ax.set_xticks(ticks)
    ax.set_xticklabels([fmt_tick(s) for s in ticks])


Y_AXIS_MAX = 160
Y_TICK_STEP = 32
WATERMARK_KEYS = 128

ColorBy = Literal["none", "connectivity", "distance-quartile"]

OKABE_ITO = [
    "#D55E00",  # Red
    "#F0E442",  # Yellow
    "#009E73",  # Green
    "#0072B2",
    "#E69F00",
    "#CC79A7",
    "#56B4E9",
    "#000000",
]
GROUP_MARKERS = ["o", "s", "^", "D", "v", "P", "X", "*"]


@dataclass(frozen=True)
class GroupStyle:
    label: str
    color: str
    marker: str


def apply_plot_style() -> None:
    plt.rcParams.update(
        {
            "font.size": 18,
            "axes.titlesize": 22,
            "axes.labelsize": 20,
            "xtick.labelsize": 18,
            "ytick.labelsize": 18,
            "lines.linewidth": 2.0,
        }
    )


def style_for_group(index: int, label: str) -> GroupStyle:
    return GroupStyle(
        label=label,
        color=OKABE_ITO[index % len(OKABE_ITO)],
        marker=GROUP_MARKERS[index % len(GROUP_MARKERS)],
    )


def load_pair_distances_km(graph_name: str) -> dict[tuple[str, str], float]:
    path = Path("graphs") / graph_name.lower() / "distances.csv"
    df = pd.read_csv(path)
    out: dict[tuple[str, str], float] = {}
    for row in df.itertuples(index=False):
        a, b = str(row.Source), str(row.Target)
        d = float(row.Distance_km)
        out[(a, b)] = d
        out[(b, a)] = d
    return out


def target_connectivity_group(
    src_node: str,
    targets: list[str],
    graph_name: str,
) -> dict[str, GroupStyle]:
    graph = get_graph_nx_graph(graph_name)  # type: ignore[arg-type]
    kappa_by_target = {t: nx.node_connectivity(graph, src_node, t) for t in targets}
    kappas = sorted(set(kappa_by_target.values()))
    styles = {k: style_for_group(i, f"κ={k}") for i, k in enumerate(kappas)}
    return {t: styles[kappa_by_target[t]] for t in targets}


def target_distance_quartile_group(
    src_node: str,
    targets: list[str],
    graph_name: str,
) -> dict[str, GroupStyle]:
    distances = load_pair_distances_km(graph_name)
    dist_by_target = {t: distances[(src_node, t)] for t in targets}
    vals = np.array(list(dist_by_target.values()))
    q1, q2, q3 = np.quantile(vals, [0.25, 0.5, 0.75])

    def quartile_label(q: int, lo: float, hi: float) -> str:
        return f"Q{q} ({lo:.0f}–{hi:.0f} km)"

    bounds = [
        (1, vals.min(), q1),
        (2, q1, q2),
        (3, q2, q3),
        (4, q3, vals.max()),
    ]
    labels = {q: quartile_label(q, lo, hi) for q, lo, hi in bounds}
    styles = {q: style_for_group(i, labels[q]) for i, (q, _, _) in enumerate(bounds)}

    def quartile_for(d: float) -> int:
        if d <= q1:
            return 1
        if d <= q2:
            return 2
        if d <= q3:
            return 3
        return 4

    return {t: styles[quartile_for(dist_by_target[t])] for t in targets}


def target_group_styles(
    src_node: str,
    targets: list[str],
    graph_name: str,
    color_by: ColorBy,
) -> dict[str, GroupStyle] | None:
    if color_by == "none":
        return None
    if color_by == "connectivity":
        return target_connectivity_group(src_node, targets, graph_name)
    if color_by == "distance-quartile":
        return target_distance_quartile_group(src_node, targets, graph_name)
    raise ValueError(f"Unknown color_by: {color_by}")


def key_count_ylim() -> tuple[float, list[int]]:
    top = Y_AXIS_MAX
    ticks = list(range(0, top + 1, Y_TICK_STEP))
    if ticks[-1] != top:
        ticks.append(top)
    return float(top), ticks


def build_key_count_series(
    src_node: str,
    events: list[KeyEvent],
    t: list[float],
) -> tuple[dict[str, list[float]], dict[str, list[int]], set[str]]:
    targets = sorted({e.tgt for e in events if e.tgt != src_node})
    cumulative = {tgt: 0 for tgt in targets}
    series_x: dict[str, list[float]] = {tgt: [] for tgt in targets}
    series_y: dict[str, list[int]] = {tgt: [] for tgt in targets}
    reached: set[str] = set()

    for i, e in enumerate(events):
        if e.tgt != src_node:
            cumulative[e.tgt] = cumulative.get(e.tgt, 0) + e.keys

        for tgt in targets:
            if tgt in reached:
                continue
            count = cumulative.get(tgt, 0)
            series_x[tgt].append(t[i])
            series_y[tgt].append(count)
            if count >= WATERMARK_KEYS:
                reached.add(tgt)

    return series_x, series_y, reached


def plot_key_count_lines(
    ax: plt.Axes,
    series_x: dict[str, list[float]],
    series_y: dict[str, list[int]],
    reached: set[str],
    group_styles: dict[str, GroupStyle] | None = None,
) -> None:
    legend_handles: dict[str, plt.Line2D] = {}
    targets = sorted(series_x.keys())

    for tgt in targets:
        xs, ys = series_x[tgt], series_y[tgt]
        if not xs:
            continue

        if group_styles is not None:
            style = group_styles[tgt]
            plot_kwargs = {"color": style.color, "linestyle": "-"}
        else:
            plot_kwargs = {}
            style = None

        (line,) = ax.plot(xs, ys, **plot_kwargs)
        color = style.color if style is not None else line.get_color()

        if tgt in reached:
            marker = style.marker if style is not None else "o"
            markersize = 5 if marker == "s" else 9
            ax.plot(xs[-1], ys[-1], marker=marker, markersize=markersize, color=color, linestyle="None")
       

        if style is not None and style.label not in legend_handles:
            legend_handles[style.label] = plt.Line2D(
                [0],
                [0],
                color=style.color,
                marker=style.marker,
                linestyle="-",
                linewidth=2.0,
                markersize=9,
                label=style.label,
            )

    if legend_handles:
        ax.legend(handles=list(legend_handles.values()), loc="lower right", frameon=True)


def finish_key_count_axes(ax: plt.Axes, halt_time_s: float | None, *, ylabel: bool = True) -> None:
    y_top, y_ticks = key_count_ylim()
    ax.set_ylim(0, y_top)
    ax.set_yticks(y_ticks)
    apply_time_ticks_5m(ax, halt_time_s)
    if ylabel:
        ax.set_ylabel("Established 256-bit keys")
    ax.grid(True, alpha=0.3)


def plot_keys_over_time(
    src_node: str,
    events: list[KeyEvent],
    halt_time_s: float | None,
    out_path: Path | None,
    graph_name: str = "GEANT",
    color_by: ColorBy = "none",
) -> None:
    apply_plot_style()

    t = make_time_axis(events, halt_time_s)
    if not t:
        raise ValueError("No key events found; nothing to plot.")

    targets = sorted({e.tgt for e in events if e.tgt != src_node})
    if not targets:
        raise ValueError("No target nodes found in log.")

    series_x, series_y, reached = build_key_count_series(src_node, events, t)
    group_styles = target_group_styles(src_node, targets, graph_name, color_by)

    fig, ax = plt.subplots(figsize=(8, 5))
    plot_key_count_lines(ax, series_x, series_y, reached, group_styles)
    finish_key_count_axes(ax, halt_time_s)
    fig.tight_layout()

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=200, bbox_inches="tight")
        plt.close(fig)
    else:
        plt.show()


def plot_side_by_side(
    logs: list[Path],
    out_path: Path,
    color_by: ColorBy = "none",
) -> None:
    if len(logs) != 2:
        raise ValueError("Provide exactly 2 logs for side-by-side plotting.")

    apply_plot_style()

    parsed = [parse_scouted_log(p) for p in logs]
    src_nodes = {src for (src, _, _, _) in parsed}
    graph_names = {g for (_, _, _, g) in parsed}
    if len(src_nodes) != 1:
        raise ValueError(f"Expected exactly one source node across logs, got: {sorted(src_nodes)}")
    if len(graph_names) != 1:
        raise ValueError(f"Expected one graph across logs, got: {sorted(graph_names)}")
    src_node = next(iter(src_nodes))
    graph_name = next(iter(graph_names))

    fig, axes = plt.subplots(1, 2, figsize=(16, 5), sharey=True)

    panel_data: list[tuple] = []

    for log_path, (src, events, halt_time_s, _) in zip(logs, parsed):
        t = make_time_axis(events, halt_time_s)
        if not t:
            raise ValueError(f"No key events found in {log_path}")

        targets = sorted({e.tgt for e in events if e.tgt != src_node})
        if not targets:
            raise ValueError(f"No target nodes found in {log_path}")

        series_x, series_y, reached = build_key_count_series(src_node, events, t)
        group_styles = target_group_styles(src_node, targets, graph_name, color_by)
        panel_data.append((log_path, series_x, series_y, reached, group_styles, halt_time_s))

    for ax, (log_path, series_x, series_y, reached, group_styles, halt_time_s) in zip(axes, panel_data):
        plot_key_count_lines(ax, series_x, series_y, reached, group_styles)
        finish_key_count_axes(ax, halt_time_s, ylabel=False)
        ax.set_title(log_path.name)

    axes[0].set_ylabel("Established 256-bit key count")
    fig.suptitle(f"Keys over time (source={src_node})", y=1.02)
    fig.tight_layout()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize scouted key establishment over time.")
    parser.add_argument(
        "--log",
        type=Path,
        action="append",
        help="Path to scouted log file. Provide once or twice (for side-by-side).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("figs/keys-over-time.pdf"),
        help="Output image path.",
    )
    parser.add_argument(
        "--color-by",
        choices=["none", "connectivity", "distance-quartile"],
        default="none",
        help="Group line color and linestyle (adds legend).",
    )
    args = parser.parse_args()

    color_by: ColorBy = args.color_by
    logs = args.log if args.log is not None else [Path("data/scouted-mar.log")]
    if len(logs) == 1:
        src_node, events, halt_time_s, graph_name = parse_scouted_log(logs[0])
        plot_keys_over_time(
            src_node=src_node,
            events=events,
            halt_time_s=halt_time_s,
            out_path=args.out,
            graph_name=graph_name,
            color_by=color_by,
        )
    elif len(logs) == 2:
        plot_side_by_side(logs, args.out, color_by=color_by)
    else:
        raise ValueError("Provide either 1 or 2 --log arguments.")


if __name__ == "__main__":
    main()
