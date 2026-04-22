from __future__ import annotations

import argparse
import re
from collections import defaultdict
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

            keys = int(m.group("keys"))
            src = m.group("src")
            tgt = m.group("tgt")
            events.append(KeyEvent(idx=len(events), src=src, tgt=tgt, keys=keys))

    if src_node is None:
        # Fallback: infer from first key line.
        if events:
            src_node = events[0].src
        else:
            raise ValueError(f"No src_nodes line and no key events found in {path}")

    return src_node, events, halt_time_s


def make_time_axis(events: list[KeyEvent], halt_time_s: float | None) -> list[float]:
    if not events:
        return []
    if halt_time_s is None or halt_time_s <= 0:
        # No timestamps in the log; fall back to event index.
        return [float(e.idx) for e in events]
    if len(events) == 1:
        return [0.0]
    # The log doesn't include per-event timestamps; approximate time by spreading
    # events uniformly over the total run time.
    return [halt_time_s * (e.idx / (len(events) - 1)) for e in events]

def apply_time_ticks_15m(ax: plt.Axes, halt_time_s: float | None) -> None:
    if halt_time_s is None:
        ax.set_xlabel("Event index (no timestamps in log)")
        return

    ax.set_xlabel("Time (h:mm)")

    total_s = max(0.0, halt_time_s)
    step_s = 15 * 60  # 15 minutes
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


def plot_keys_over_time(
    src_node: str,
    events: list[KeyEvent],
    halt_time_s: float | None,
    out_path: Path | None,
) -> None:
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

    # Collect all targets (exclude the source itself).
    targets = sorted({e.tgt for e in events if e.tgt != src_node})
    cumulative = {tgt: 0 for tgt in targets}

    # Per target, build a step-like cumulative curve with points at every event.
    series_x: dict[str, list[float]] = {tgt: [] for tgt in targets}
    series_y: dict[str, list[int]] = {tgt: [] for tgt in targets}

    for i, e in enumerate(events):
        if e.tgt != src_node:
            cumulative[e.tgt] = cumulative.get(e.tgt, 0) + e.keys

        for tgt in targets:
            series_x[tgt].append(t[i])
            series_y[tgt].append(cumulative.get(tgt, 0))

    fig, ax = plt.subplots(figsize=(8, 5))
    for tgt in targets:
        ax.plot(series_x[tgt], series_y[tgt])

    watermark = 128
    # ax.axhline(watermark, color="black", linestyle="--", linewidth=2.0, alpha=0.9)
    ax.set_ylim(0, watermark)
    ax.set_yticks(list(range(0, watermark + 1, 32)))

    apply_time_ticks_15m(ax, halt_time_s)

    ax.set_ylabel("Established key count")
    # ax.set_title(f"Keys over time (source={src_node})")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=200, bbox_inches="tight")
    else:
        plt.show()

def plot_side_by_side(logs: list[Path], out_path: Path) -> None:
    if len(logs) != 2:
        raise ValueError("Provide exactly 2 logs for side-by-side plotting.")

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

    parsed = [parse_scouted_log(p) for p in logs]
    src_nodes = {src for (src, _, _) in parsed}
    if len(src_nodes) != 1:
        raise ValueError(f"Expected exactly one source node across logs, got: {sorted(src_nodes)}")
    src_node = next(iter(src_nodes))

    fig, axes = plt.subplots(1, 2, figsize=(16, 5), sharey=True)
    watermark = 128

    for ax, log_path, (src, events, halt_time_s) in zip(axes, logs, parsed):
        t = make_time_axis(events, halt_time_s)
        if not t:
            raise ValueError(f"No key events found in {log_path}")

        targets = sorted({e.tgt for e in events if e.tgt != src_node})
        cumulative = {tgt: 0 for tgt in targets}

        series_x: dict[str, list[float]] = {tgt: [] for tgt in targets}
        series_y: dict[str, list[int]] = {tgt: [] for tgt in targets}

        for i, e in enumerate(events):
            if e.tgt != src_node:
                cumulative[e.tgt] = cumulative.get(e.tgt, 0) + e.keys
            for tgt in targets:
                series_x[tgt].append(t[i])
                series_y[tgt].append(cumulative.get(tgt, 0))

        for tgt in targets:
            ax.plot(series_x[tgt], series_y[tgt])

        # ax.axhline(watermark, color="black", linestyle="--", linewidth=2.0, alpha=0.9)
        ax.set_ylim(0, watermark)
        ax.set_yticks(list(range(0, watermark + 1, 32)))
        apply_time_ticks_15m(ax, halt_time_s)
        ax.grid(True, alpha=0.3)
        ax.set_title(log_path.name)

    axes[0].set_ylabel("Established key count")
    fig.suptitle(f"Keys over time (source={src_node})", y=1.02)
    fig.tight_layout()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")


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
        default=Path("data/scouted-geant-keys-over-time.png"),
        help="Output image path.",
    )
    args = parser.parse_args()

    logs = args.log if args.log is not None else [Path("data/scouted-geant.log")]
    if len(logs) == 1:
        src_node, events, halt_time_s = parse_scouted_log(logs[0])
        plot_keys_over_time(src_node=src_node, events=events, halt_time_s=halt_time_s, out_path=args.out)
    elif len(logs) == 2:
        plot_side_by_side(logs, args.out)
    else:
        raise ValueError("Provide either 1 or 2 --log arguments.")


if __name__ == "__main__":
    main()

