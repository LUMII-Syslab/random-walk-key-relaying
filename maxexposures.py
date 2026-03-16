from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


PROCESSING_RE = re.compile(
    r"^Processing\s+(?P<nodes>\d+)\s+nodes\.\.\.\s+with\s+erase_loops=(?P<erase_loops>True|False)$"
)
EXPOSURE_RE = re.compile(
    r"^(?P<variant>[A-Z]+):\s+max_exposure=(?P<max_exposure>\d+(?:\.\d+)?)\s+"
    r"s=(?P<src>\d+)\s+t=(?P<tgt>\d+)\s+v=(?P<via>\d+)$"
)


@dataclass(frozen=True)
class MaxExposurePoint:
    variant: str
    max_exposure: float
    nodes: int
    erase_loops: bool
    src: int
    tgt: int
    via: int


def parse_scaling_file(path: Path) -> dict[str, MaxExposurePoint]:
    best_by_variant: dict[str, MaxExposurePoint] = {}
    current_nodes: int | None = None
    current_erase_loops: bool | None = None

    for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("-"):
            continue

        processing_match = PROCESSING_RE.match(line)
        if processing_match:
            current_nodes = int(processing_match.group("nodes"))
            current_erase_loops = processing_match.group("erase_loops") == "True"
            continue

        exposure_match = EXPOSURE_RE.match(line)
        if not exposure_match:
            continue

        if current_nodes is None or current_erase_loops is None:
            raise ValueError(
                f"Found exposure entry before processing header at line {line_no}: {raw_line!r}"
            )

        point = MaxExposurePoint(
            variant=exposure_match.group("variant"),
            max_exposure=float(exposure_match.group("max_exposure")),
            nodes=current_nodes,
            erase_loops=current_erase_loops,
            src=int(exposure_match.group("src")),
            tgt=int(exposure_match.group("tgt")),
            via=int(exposure_match.group("via")),
        )

        current_best = best_by_variant.get(point.variant)
        if current_best is None or point.max_exposure > current_best.max_exposure:
            best_by_variant[point.variant] = point

    return best_by_variant


def format_result(point: MaxExposurePoint) -> str:
    return (
        f"{point.variant}: max_exposure={point.max_exposure:.3f} "
        f"at nodes={point.nodes}, erase_loops={point.erase_loops}, "
        f"s={point.src}, t={point.tgt}, v={point.via}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find the maximum exposure reached by each walk variant in scaling.txt."
    )
    parser.add_argument(
        "scaling_file",
        nargs="?",
        default=Path(__file__).resolve().parent / "data" / "scaling.txt",
        type=Path,
        help="Path to the scaling results file.",
    )
    args = parser.parse_args()

    best_by_variant = parse_scaling_file(args.scaling_file)
    for variant in sorted(best_by_variant):
        print(format_result(best_by_variant[variant]))


if __name__ == "__main__":
    main()
