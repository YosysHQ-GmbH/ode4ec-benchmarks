import json
import re
import shutil
from pathlib import Path

RESULT_COLUMNS = (
    "cells",
    "result",
    "process_time",
    "process_secs",
    "clock_time",
    "clock_secs",
)

MARKER_FILES = [
    "PASS",
    "FAIL",
    "UNKNOWN",
    "ERROR",
    "TIMEOUT",
    "CANCELLED",
    "HARDTIMEOUT",
]
PROCESS_TIME_PATTERN = re.compile(
    r"^Elapsed process time \[H:MM:SS \(secs\)\]: (\d+:\d+:\d+) \((\d+)\)$",
    flags=re.MULTILINE,
)
CLOCK_TIME_PATTERN = re.compile(
    r"^Elapsed clock time \[H:MM:SS \(secs\)\]: (\d+:\d+:\d+) \((\d+)\)$",
    flags=re.MULTILINE,
)
CELLS_PATTERN = re.compile(
    r"^\s*(\d+)\s+([-+]?\d*\.?\d+(?:[Ee][-+]?\d+)?)\s+cells\s*$"
)


def task_dir_name(task: str, sby_file: str) -> str:
    return f"{sby_file.split('.')[0]}_{task}"


def split_task_dir_name(name: str) -> tuple[str, str] | None:
    if name.startswith("miter_extra_asserts_"):
        return name[len("miter_extra_asserts_") :], "miter_extra_asserts.sby"
    if name.startswith("miter_"):
        return name[len("miter_") :], "miter.sby"
    return None


def read_marker(task_dir: Path) -> dict | None:
    for marker in MARKER_FILES:
        marker_path = task_dir / marker
        if marker_path.exists():
            content = marker_path.read_text(encoding="utf-8-sig")
            process_match = PROCESS_TIME_PATTERN.search(content)
            clock_match = CLOCK_TIME_PATTERN.search(content)
            return {
                "result": marker,
                "process_time": process_match.group(1) if process_match else None,
                "process_secs": int(process_match.group(2))
                if process_match
                else None,
                "clock_time": clock_match.group(1) if clock_match else None,
                "clock_secs": int(clock_match.group(2)) if clock_match else None,
            }
    return None


def read_cells_from_stats_file(export_dir: Path) -> int | None:
    stats_path = export_dir / "stat.txt"
    if not stats_path.exists():
        return None
    content = stats_path.read_text(encoding="utf-8-sig")
    for line in content.split("\n"):
        m = CELLS_PATTERN.match(line)
        if m:
            return int(m.group(1))
    return None


def _cache_path(run_dir: Path) -> Path:
    return run_dir / "results_cache.json"


def load_results_cache(run_dir: Path) -> dict:
    path = _cache_path(run_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def record_result(
    run_dir: Path,
    export_dir_name: str,
    task: str,
    sby_file: str,
    row: dict,
    params: dict | None = None,
) -> None:
    path = _cache_path(run_dir)
    cache = load_results_cache(run_dir)
    entry = cache.setdefault(export_dir_name, {"params": {}, "tasks": {}})
    if params is not None:
        entry["params"] = params
    entry["tasks"][task_dir_name(task, sby_file)] = {
        k: row.get(k) for k in RESULT_COLUMNS
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(cache, indent=2, sort_keys=True))
    tmp.replace(path)


def prune_task_dir(export_dir: Path, task: str, sby_file: str) -> None:
    task_dir = export_dir / task_dir_name(task, sby_file)
    if not task_dir.is_dir():
        return
    for entry in task_dir.iterdir():
        if entry.name in MARKER_FILES:
            continue
        if entry.is_dir():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)
