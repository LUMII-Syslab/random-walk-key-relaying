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


def plot_keys_over_time(
    src_node: str,
    events: list[KeyEvent],
    halt_time_s: float | None,
    out_path: Path | None,
) -> None:
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

    fig, ax = plt.subplots(figsize=(14, 8))
    for tgt in targets:
        ax.plot(series_x[tgt], series_y[tgt], linewidth=1.2, label=tgt)

    watermark = 128
    ax.axhline(watermark, color="black", linestyle="--", linewidth=1.2, alpha=0.8, label=f"watermark={watermark}")

    if halt_time_s is None:
        ax.set_xlabel("Event index (no timestamps in log)")
        title_suffix = " (x-axis = event index)"
    else:
        ax.set_xlabel("Time (s) (approximated from total run time)")
        title_suffix = " (x-axis time approximated)"

    ax.set_ylabel("Establishable key count (cumulative)")
    ax.set_title(f"Scout-based key relaying: keys over time (source={src_node}){title_suffix}")
    ax.grid(True, alpha=0.3)

    # Large legend: put it outside.
    ax.legend(
        loc="center left",
        bbox_to_anchor=(1.02, 0.5),
        ncol=1,
        fontsize="small",
        frameon=False,
    )
    fig.tight_layout()

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(out_path, dpi=200, bbox_inches="tight")
    else:
        plt.show()


def main() -> None:
    parser = argparse.ArgumentParser(description="Visualize scouted key establishment over time.")
    parser.add_argument(
        "--log",
        type=Path,
        default=Path("data/scouted-geant.log"),
        help="Path to scouted log file.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/scouted-geant-keys-over-time.png"),
        help="Output PNG path.",
    )
    args = parser.parse_args()

    src_node, events, halt_time_s = parse_scouted_log(args.log)
    plot_keys_over_time(src_node=src_node, events=events, halt_time_s=halt_time_s, out_path=args.out)


if __name__ == "__main__":
    main()

