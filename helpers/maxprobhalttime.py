"""
Query helper for the "max consume prob vs halt time" datapoint.

This module provides a single-datapoint query function with on-disk caching,
so scripts can call it repeatedly without needing separate "acquire vs load"
phases.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
import subprocess
from typing import Any, Optional


def _repo_root_from_file() -> Path:
    current_dir = Path(__file__).resolve().parent
    for candidate in (current_dir, *current_dir.parents):
        if (candidate / ".git").exists():
            return candidate
    raise FileNotFoundError(f"Could not locate git repo root from {__file__}")


@dataclass(frozen=True)
class MaxProbHaltTimeParams:
    max_consume_prob: float
    halt_at_keys: int

    watermark_sz: int = 256
    scenario: str = "MIL"
    edges_csv: str = "graphs/geant/biconn.csv"


_built_scouted2 = False


def _ensure_built() -> None:
    global _built_scouted2
    if _built_scouted2:
        return
    repo_root = _repo_root_from_file()
    subprocess.run(["make", "build/scouted2"], cwd=str(repo_root / "cpp"), check=True)
    _built_scouted2 = True


def _default_cache_path() -> Path:
    repo_root = _repo_root_from_file()
    cache_dir = repo_root / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "maxprobhalttime.json"


def _stable_key(params: MaxProbHaltTimeParams) -> str:
    payload = json.dumps(asdict(params), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_cache(cache_path: Path) -> dict[str, Any]:
    if not cache_path.exists():
        return {"version": 1, "entries": {}}
    with cache_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "entries" not in data:
        return {"version": 1, "entries": {}}
    if not isinstance(data.get("entries"), dict):
        return {"version": 1, "entries": {}}
    return data


def _write_cache(cache_path: Path, data: dict[str, Any]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp_path, cache_path)


def _run_simulation(params: MaxProbHaltTimeParams) -> float:
    _ensure_built()
    repo_root = _repo_root_from_file()
    edges_path = repo_root / params.edges_csv
    out = subprocess.check_output(
        [
            "./build/scouted2",
            "-S",
            params.scenario,
            "-e",
            str(edges_path),
            "--halt-at-keys",
            str(int(params.halt_at_keys)),
            "--max-consume-prob",
            str(float(params.max_consume_prob)),
            "--watermark-sz",
            str(int(params.watermark_sz)),
        ],
        cwd=str(repo_root / "cpp"),
    )
    for line in out.decode("utf-8").split("\n"):
        if "Halted at" in line:
            return float(line.split(" ")[2])
    raise RuntimeError("Could not parse halt time from scouted2 output")


def query_maxprob_halt_time(
    *,
    max_consume_prob: float,
    halt_at_keys: int,
    watermark_sz: int = 256,
    scenario: str = "MIL",
    edges_csv: str = "graphs/geant/biconn.csv",
    cache_path: Optional[str | Path] = None,
    force_recompute: bool = False,
) -> float:
    """
    Query a single datapoint (max_consume_prob, halt_at_keys, ...) returning the halted time.

    - Uses an on-disk JSON cache (default: repo-root `/.cache/maxprobhalttime.json`)
    - Set force_recompute=True to bypass cache and overwrite the entry.
    """
    params = MaxProbHaltTimeParams(
        max_consume_prob=float(max_consume_prob),
        halt_at_keys=int(halt_at_keys),
        watermark_sz=int(watermark_sz),
        scenario=str(scenario),
        edges_csv=str(edges_csv),
    )

    cache_file = Path(cache_path) if cache_path is not None else _default_cache_path()
    key = _stable_key(params)

    if not force_recompute:
        cache = _read_cache(cache_file)
        entry = cache.get("entries", {}).get(key)
        if isinstance(entry, dict) and entry.get("ok") is True:
            value = entry.get("value")
            if isinstance(value, (int, float)):
                return float(value)

    value = _run_simulation(params)

    cache = _read_cache(cache_file)
    entries = cache.setdefault("entries", {})
    entries[key] = {"ok": True, "value": float(value), "params": asdict(params)}
    _write_cache(cache_file, cache)
    return float(value)
