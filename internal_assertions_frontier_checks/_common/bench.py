import re
import shutil
import subprocess
import sys
from collections import deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

import polars as pl

from .plots import generate_plots


@contextmanager
def atomic_build_dir(final_dir: Path) -> Iterator[Path]:
    scratch_dir = final_dir.with_name(f".build-{final_dir.name}")
    if scratch_dir.exists():
        shutil.rmtree(scratch_dir)
    scratch_dir.mkdir(parents=True)
    try:
        yield scratch_dir
    except BaseException:
        shutil.rmtree(scratch_dir, ignore_errors=True)
        raise
    else:
        scratch_dir.rename(final_dir)


RESULT_COLUMNS = (
    "cells",
    "result",
    "process_time",
    "process_secs",
    "clock_time",
    "clock_secs",
)


def live_window_stream(stream: TextIO, num_lines: int = 5, indent: int = 1) -> None:
    window = deque(maxlen=num_lines)
    lines_currently_displayed = 0
    prefix = "    " * indent
    term_width = shutil.get_terminal_size((80, 20)).columns

    for line in stream:
        clean_line = line.rstrip("\n")

        available_width = term_width - len(prefix)
        if len(clean_line) > available_width:
            clean_line = clean_line[: max(available_width - 1, 0)]

        window.append(prefix + clean_line)

        if lines_currently_displayed > 0:
            sys.stdout.write(f"\033[{lines_currently_displayed}A")

        for w_line in window:
            sys.stdout.write(f"\033[2K\r{w_line}\n")

        sys.stdout.flush()
        lines_currently_displayed = len(window)

    if lines_currently_displayed > 0:
        sys.stdout.write(f"\033[{lines_currently_displayed}A")
        for _ in range(lines_currently_displayed):
            sys.stdout.write("\033[2K\n")
        sys.stdout.write(f"\033[{lines_currently_displayed}A")
        sys.stdout.flush()


class SetupBase:
    MARKER_FILES = ["PASS", "FAIL", "UNKNOWN", "ERROR", "TIMEOUT", "CANCELLED"]
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

    export_dir: Path
    name: str
    params: dict

    def row(self) -> dict:
        return {"name": self.name, **self.params}

    def _read_marker_file(self, task: str, sby_file: str) -> dict:
        for marker in self.MARKER_FILES:
            marker_path = self.export_dir / f"{sby_file.split('.')[0]}_{task}" / marker
            if marker_path.exists():
                content = marker_path.read_text(encoding="utf-8-sig")
                process_match = self.PROCESS_TIME_PATTERN.search(content)
                clock_match = self.CLOCK_TIME_PATTERN.search(content)
                return {
                    "result": marker,
                    "process_time": process_match.group(1) if process_match else None,
                    "process_secs": int(process_match.group(2))
                    if process_match
                    else None,
                    "clock_time": clock_match.group(1) if clock_match else None,
                    "clock_secs": int(clock_match.group(2)) if clock_match else None,
                }
        return {
            "result": "---",
            "process_time": None,
            "process_secs": None,
            "clock_time": None,
            "clock_secs": None,
        }

    def read_cells_from_stats_file(self) -> int | None:
        stats_path = self.export_dir / "stat.txt"
        content = stats_path.read_text(encoding="utf-8-sig")
        for line in content.split("\n"):
            m = self.CELLS_PATTERN.match(line)
            if m:
                return int(m.group(1))
        return None

    def _read_result(self, task: str, sby_file: str) -> dict | None:
        marker_info = self._read_marker_file(task, sby_file)
        if marker_info["result"] == "---":
            return None
        return {
            "name": self.name,
            "cells": self.read_cells_from_stats_file(),
            **marker_info,
        }

    def run_task(self, task: str, sby_file: str) -> dict:
        cached = self._read_result(task, sby_file)
        if cached is not None:
            return cached

        command = ["sby", "-j", "4", "--statuscancels", "-f", sby_file, task]
        process = subprocess.Popen(
            command,
            cwd=self.export_dir,
            stdout=subprocess.PIPE,
            text=True,
        )

        live_window_stream(process.stdout, num_lines=10)
        process.wait()

        result = self._read_result(task, sby_file)
        assert result is not None, (
            f"sby produced no result marker for {task}/{sby_file} in {self.export_dir}"
        )
        return result


def tasks_in(content: str) -> set[str]:
    tasks = set()
    in_task_section = False
    for line in content.splitlines():
        line = line.split("#", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            in_task_section = line == "[tasks]"
            continue
        if in_task_section and line:
            tasks.add(line)
    return tasks


def parse_tasks(content: str) -> list[str]:
    return sorted(tasks_in(content))


def find_frontier(run: Callable[[int], bool], start: int = 8, min_n: int = 1) -> int:
    lo, hi = min_n - 1, start
    while run(hi):
        lo, hi = hi, hi * 2
    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if run(mid) else (lo, mid)
    return lo


def run_benchmark(
    setup_gen: Callable[[int], SetupBase],
    tasks: list[str],
    start: int = 8,
    min_n: int = 1,
) -> dict[str, pl.DataFrame]:
    task_frames: dict[str, pl.DataFrame] = {}
    frontiers_miter: dict[str, int] = {}
    frontiers_internal_asserts: dict[str, int] = {}

    for task in tasks:
        visited_setups: dict[int, dict] = {}
        visited_miter: dict[int, dict] = {}
        visited_internal_asserts: dict[int, dict] = {}

        def make_runner(
            label: str, sby_file: str, sink: dict[int, dict]
        ) -> Callable[[int], bool]:
            def run(n: int) -> bool:
                try:
                    setup = setup_gen(n)
                except Exception as exc:
                    name = f"<setup-failed n={n}>"
                    print(f"Setup failed: {label} {task} n={n}: {exc}")
                    visited_setups[n] = {"name": name}
                    sink[n] = {
                        "name": name,
                        "cells": None,
                        "result": "SETUP_ERROR",
                        "process_time": None,
                        "process_secs": None,
                        "clock_time": None,
                        "clock_secs": None,
                    }
                    return False
                visited_setups[n] = setup.row()
                print(f"Running: {label} {task} {setup.name}")
                row = setup.run_task(task, sby_file)
                sink[n] = row
                return row["result"] == "PASS"

            return run

        run_miter = make_runner("MI", "miter.sby", visited_miter)
        run_internal_asserts = make_runner(
            "IA", "miter_extra_asserts.sby", visited_internal_asserts
        )

        frontiers_miter[task] = find_frontier(run_miter, start=start, min_n=min_n)
        frontiers_internal_asserts[task] = find_frontier(
            run_internal_asserts, start=start, min_n=min_n
        )

        all_n = sorted(visited_setups)
        setup_rows = [{"step": i, **visited_setups[n]} for i, n in enumerate(all_n)]
        miter_rows = [visited_miter[n] for n in sorted(visited_miter)]
        internal_assert_rows = [
            visited_internal_asserts[n] for n in sorted(visited_internal_asserts)
        ]

        setups_df = pl.DataFrame(setup_rows)
        miter_df = pl.DataFrame(miter_rows).rename(
            {c: f"{c}_miter" for c in RESULT_COLUMNS}
        )
        internal_asserts_df = pl.DataFrame(internal_assert_rows).rename(
            {c: f"{c}_internal_asserts" for c in RESULT_COLUMNS}
        )

        task_frames[task] = (
            setups_df.join(miter_df, on="name", how="left")
            .join(internal_asserts_df, on="name", how="left")
            .sort("step")
        )
    print()

    for task in tasks:
        print(f"=== Task {task} ===")
        print(task_frames[task])
        print(f"MI frontier: {frontiers_miter[task]}")
        print(f"IA frontier: {frontiers_internal_asserts[task]}")
        print()

    return task_frames


Benchmark = (
    tuple[str, Callable[[int], SetupBase], list[str], int]
    | tuple[str, Callable[[int], SetupBase], list[str], int, int]
)


def run_and_report(benchmarks: list[Benchmark], run_dir: Path) -> None:
    pl.Config.set_tbl_rows(-1)
    pl.Config.set_tbl_cols(-1)
    pl.Config.set_fmt_str_lengths(60)
    pl.Config.set_tbl_width_chars(240)

    all_frames: list[pl.DataFrame] = []
    for benchmark in benchmarks:
        name, setup_gen, tasks, start, *rest = benchmark
        min_n = rest[0] if rest else 1
        print(f"=== {name} ===")
        task_frames = run_benchmark(setup_gen, tasks, start=start, min_n=min_n)
        for task, df in task_frames.items():
            all_frames.append(
                df.with_columns(
                    pl.lit(name).alias("benchmark"), pl.lit(task).alias("task")
                )
            )

    results = pl.concat(all_frames, how="vertical_relaxed")
    run_dir.mkdir(parents=True, exist_ok=True)
    results.write_parquet(run_dir / "results.parquet")
    results.write_csv(run_dir / "results.csv")
    print(f"Wrote combined results to {run_dir / 'results.parquet'} and .csv")

    plot_paths = generate_plots(results, run_dir / "plots")
    print(f"Wrote {len(plot_paths)} plots to {run_dir / 'plots'}")
