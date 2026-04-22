from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt

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


@dataclass(frozen=True)
class KeyEvent:
    idx: int
    src: str
    tgt: str
    keys: int


def parse_scouted_log(path: Path) -> tuple[str, list[KeyEvent], float | None]:
    src_node: str | None = None
    events: list[KeyEvent] = []
    halt_time_s: float | None = None

    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            m = SRC_RE.match(line)
            if m:
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

            events.append(
                KeyEvent(
                    idx=len(events),
                    src=m.group("src"),
                    tgt=m.group("tgt"),
                    keys=int(m.group("keys")),
                )
            )

    if src_node is None:
        if events:
            src_node = events[0].src
        else:
            raise ValueError(f"No src_nodes line and no key events found in {path}")

    return src_node, events, halt_time_s


def make_time_axis(events: list[KeyEvent], halt_time_s: float | None) -> list[float]:
    if not events:
        return []
    if halt_time_s is None or halt_time_s <= 0:
        return [float(e.idx) for e in events]
    if len(events) == 1:
        return [0.0]
    return [halt_time_s * (e.idx / (len(events) - 1)) for e in events]


def apply_time_ticks_15m(ax: plt.Axes, halt_time_s: float | None) -> None:
    if halt_time_s is None:
        ax.set_xlabel("Event index (no timestamps in log)")
        return

    ax.set_xlabel("Time (h:mm)")

    total_s = max(0.0, halt_time_s)
    step_s = 15 * 60
    ticks = [0.0]
    x = step_s
    while x <= total_s + 1e-9:
        ticks.append(float(x))
        x += step_s

    def fmt_tick(sec: float) -> str:
        m = int(round(sec / 60.0))
        h = m // 60
        mm = m % 60
        return f"{h}:{mm:02d}"

    ax.set_xticks(ticks)
    ax.set_xticklabels([fmt_tick(s) for s in ticks])


def fmt_time_or_idx(x: float, halt_time_s: float | None) -> str:
    if halt_time_s is None:
        if abs(x - round(x)) < 1e-9:
            return f"idx={int(round(x))}"
        return f"idx={x:.3f}"
    total_s = max(0.0, float(x))
    h = int(total_s // 3600)
    m = int((total_s % 3600) // 60)
    s = total_s - (3600 * h + 60 * m)
    return f"{h}:{m:02d}:{s:06.3f}"


def compute_threshold_reach_times(
    src_node: str,
    events: list[KeyEvent],
    t: list[float],
    thresholds: list[int],
) -> dict[int, dict[str, float]]:
    targets = sorted({e.tgt for e in events if e.tgt != src_node})
    cumulative: dict[str, int] = {tgt: 0 for tgt in targets}
    reach_time: dict[int, dict[str, float]] = {thr: {} for thr in thresholds}

    for i, e in enumerate(events):
        if e.tgt != src_node:
            cumulative[e.tgt] = cumulative.get(e.tgt, 0) + e.keys
        for thr in thresholds:
            for tgt in targets:
                if tgt in reach_time[thr]:
                    continue
                if cumulative.get(tgt, 0) >= thr:
                    reach_time[thr][tgt] = t[i]
    return reach_time


def plot_threshold_reach_counts(
    src_node: str,
    events: list[KeyEvent],
    halt_time_s: float | None,
    thresholds: list[int],
    out_path: Path | None,
) -> None:
    # Colorblind-friendly palette (Okabe-Ito) + redundant encodings (linestyle/marker)
    # so lines are distinguishable even in grayscale.
    okabe_ito = [
        "#0072B2",  # blue
        "#E69F00",  # orange
        "#56B4E9",  # sky blue
        "#009E73",  # bluish green
        "#F0E442",  # yellow
        "#CC79A7",  # reddish purple
        "#D55E00",  # vermillion
        "#000000",  # black
    ]
    linestyles = ["-", "--", "-.", ":", (0, (5, 2)), (0, (2, 2)), (0, (3, 1, 1, 1)), (0, (1, 1))]
    markers = ["o", "s", "^", "D", "v", "P", "X", "*"]

    def style_for(i: int) -> dict:
        return {
            "color": okabe_ito[i % len(okabe_ito)],
            "linestyle": linestyles[i % len(linestyles)],
            "marker": markers[i % len(markers)],
            "markersize": 9,
            "markevery": max(1, int(len(events) / 25)) if events else 1,
        }

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

    t = make_time_axis(events, halt_time_s)
    if not t:
        raise ValueError("No key events found; nothing to plot.")

    targets = sorted({e.tgt for e in events if e.tgt != src_node})
    if not targets:
        raise ValueError("No target nodes found in log.")

    reach_time = compute_threshold_reach_times(
        src_node=src_node,
        events=events,
        t=t,
        thresholds=thresholds,
    )
    print("Threshold reach times:")
    for thr in thresholds:
        reached = reach_time.get(thr, {})
        print(f"  {thr} keys:")
        if not reached:
            print("    (none)")
            continue
        for tgt, when in sorted(reached.items(), key=lambda kv: kv[1],reverse=True):
            print(f"    {tgt}: {fmt_time_or_idx(when, halt_time_s)}")
            break

    cumulative: dict[str, int] = {tgt: 0 for tgt in targets}
    reached: dict[int, set[str]] = {thr: set() for thr in thresholds}

    xs: dict[int, list[float]] = {thr: [] for thr in thresholds}
    ys: dict[int, list[int]] = {thr: [] for thr in thresholds}

    for i, e in enumerate(events):
        if e.tgt != src_node:
            cumulative[e.tgt] = cumulative.get(e.tgt, 0) + e.keys

        # Update reached sets at this time.
        for thr in thresholds:
            for tgt in targets:
                if tgt in reached[thr]:
                    continue
                if cumulative.get(tgt, 0) >= thr:
                    reached[thr].add(tgt)

            xs[thr].append(t[i])
            ys[thr].append(len(reached[thr]))

    fig, ax = plt.subplots(figsize=(8, 5))

    for i, thr in enumerate(thresholds):
        ax.plot(xs[thr], ys[thr], label=f"{thr} keys", **style_for(i))

    ax.set_ylabel("No. of nodes satisfied")
    apply_time_ticks_15m(ax, halt_time_s)
    ax.set_ylim(0, len(targets))
    ax.grid(True, alpha=0.3)
    # ax.set_title(f"How fast nodes reach key thresholds (source={src_node})")

    # Legend is useful here (only 5 lines) and won't clutter the plot much.
    # ax.legend(frameon=False, ncol=len(thresholds), loc="upper left")
    ax.legend(loc="lower right")

    fig.tight_layout()
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=200, bbox_inches="tight")
    else:
        plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Plot how quickly nodes reach key thresholds in scouted logs."
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=Path("data/scouted-geant.log"),
        help="Path to scouted log file.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/scouted-geant-threshold-reach.png"),
        help="Output image path.",
    )
    parser.add_argument(
        "--thresholds",
        type=str,
        default="1,8,16,32,64,128",
        help="Comma-separated list of thresholds.",
    )
    args = parser.parse_args()

    thresholds = [int(x) for x in args.thresholds.split(",") if x.strip()]
    thresholds = sorted(set(thresholds))
    if not thresholds:
        raise ValueError("No thresholds provided.")

    src_node, events, halt_time_s = parse_scouted_log(args.log)
    plot_threshold_reach_counts(
        src_node=src_node,
        events=events,
        halt_time_s=halt_time_s,
        thresholds=thresholds,
        out_path=args.out,
    )

if __name__ == "__main__":
    main()

