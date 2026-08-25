# /// script
# requires-python = ">=3.14"
# ///
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common.results_cache import (
    MARKER_FILES,
    prune_task_dir,
    read_cells_from_stats_file,
    read_marker,
    record_result,
    split_task_dir_name,
)


def _dir_size(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def scan_export_dir(export_dir: Path) -> dict[str, tuple[str, str, dict]]:
    found = {}
    for child in sorted(export_dir.iterdir()):
        if not child.is_dir():
            continue
        split = split_task_dir_name(child.name)
        if split is None:
            continue
        marker_info = read_marker(child)
        if marker_info is None:
            continue
        task, sby_file = split
        row = {**marker_info, "cells": read_cells_from_stats_file(export_dir)}
        found[child.name] = (task, sby_file, row)
    return found


def migrate_run_dir(run_dir: Path, apply: bool) -> tuple[int, int]:
    migrated = 0
    reclaimed = 0
    for export_dir in sorted(run_dir.iterdir()):
        if not export_dir.is_dir() or export_dir.name.startswith("."):
            continue
        for name, (task, sby_file, row) in scan_export_dir(export_dir).items():
            task_dir = export_dir / name
            before = _dir_size(task_dir)
            marker_size = sum(
                (task_dir / m).stat().st_size
                for m in MARKER_FILES
                if (task_dir / m).exists()
            )
            reclaimed += before - marker_size
            migrated += 1
            if apply:
                record_result(run_dir, export_dir.name, task, sby_file, row)
                prune_task_dir(export_dir, task, sby_file)
    return migrated, reclaimed


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "benchmark_dirs",
        nargs="*",
        type=Path,
        help="benchmark directories to migrate (default: all with a run/ dir)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually migrate and delete (default: dry run, changes nothing)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    benchmark_dirs = args.benchmark_dirs or [
        p for p in sorted(root.iterdir()) if p.is_dir() and (p / "run").is_dir()
    ]

    total_migrated = 0
    total_reclaimed = 0
    for bench_dir in benchmark_dirs:
        run_dir = bench_dir / "run"
        if not run_dir.is_dir():
            print(f"skip {bench_dir}: no run/ directory")
            continue
        migrated, reclaimed = migrate_run_dir(run_dir, apply=args.apply)
        total_migrated += migrated
        total_reclaimed += reclaimed
        verb = "migrated" if args.apply else "would migrate"
        amount = "reclaimed" if args.apply else "would reclaim"
        print(
            f"{bench_dir.name}: {verb} {migrated} finished task dirs, "
            f"{amount} {reclaimed / 1e9:.2f} GB"
        )

    print()
    if args.apply:
        print(
            f"TOTAL: {total_migrated} task dirs, {total_reclaimed / 1e9:.2f} GB reclaimed"
        )
    else:
        print(
            f"TOTAL (dry run, nothing changed): {total_migrated} task dirs, "
            f"{total_reclaimed / 1e9:.2f} GB would be reclaimed -- pass --apply to do it"
        )


if __name__ == "__main__":
    main()
