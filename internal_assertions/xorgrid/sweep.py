#!/usr/bin/env python3
"""Scaling-frontier search driver for the xorgrid benchmark.

For each (target, flavor) pair, doubles SIZE until a run stops solving within
the per-task budget, then binary-refines between the last solved and first
unsolved size. Reads per-run status directly from `run/check_*/status` /
marker files (report.py is not touched by this script). Writes
`results/sweep_log.json` (raw, resumable log) and `results/frontier.json`
(summary: target -> flavor -> max solved SIZE).
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

XORGRID_DIR = Path(__file__).resolve().parent
RUN_DIR = XORGRID_DIR / "run"
RESULTS_DIR = XORGRID_DIR / "results"
SWEEP_LOG_PATH = RESULTS_DIR / "sweep_log.json"
FRONTIER_PATH = RESULTS_DIR / "frontier.json"

# Must match the Makefile's fixed defaults (I, F) -- gen_xorgrid.py asserts
# I <= SIZE*SIZE*F at generation time.
FIXED_I = 32
FIXED_F = 8

TASK_BUDGET = 600  # matches the `timeout 600` set in every .sby.in task
GEN_SYNTH_OVERHEAD = 600  # generation/elaboration/synthesis before any solver starts
ORFS_EXTRA_OVERHEAD = 1800  # real OpenROAD synthesis is slow
# eqy's `combine` step has shown pathological (multi-GB log, 15+ minute)
# blowups in this repo (see serv/run/check_eqy_yosys/combine.log) that are
# NOT bounded by the `timeout 600` inside its `[strategy sby]` block, since
# that only covers the solver step, not combine. This is a defensive
# external cap, not a claim that eqy itself is expected to take this long.
EQY_TIMEOUT_CAP = 1800

MARKER_FILES = ["PASS", "FAIL", "UNKNOWN", "ERROR", "TIMEOUT", "CANCELLED"]

# target key -> (make target base, leaf basename, prove-mode task names or
# None for eqy, which has no prove/bmc split -- see README.md caveat)
TARGETS = {
    "eqy": {"make": "eqy", "leaf": "eqy", "tasks": None},
    "sby": {"make": "sby", "leaf": "sby", "tasks": ("task_abc", "task_aiger")},
    "miter": {
        "make": "custom-miter",
        "leaf": "custom_miter",
        "tasks": ("task_abc", "task_aiger"),
    },
    "miter-extra-asserts": {
        "make": "custom-miter-extra-asserts",
        "leaf": "custom_miter_with_extra_asserts",
        "tasks": ("task_abc", "task_aiger"),
    },
}


def subprocess_timeout_for(target: str, flavor: str) -> int:
    if target == "eqy":
        base = EQY_TIMEOUT_CAP
    else:
        n_tasks = len(TARGETS[target]["tasks"])
        base = n_tasks * TASK_BUDGET + GEN_SYNTH_OVERHEAD
    if flavor == "orfs":
        base += ORFS_EXTRA_OVERHEAD
    return base


def read_marker_status(leaf_dir: Path) -> str | None:
    for marker in MARKER_FILES:
        if (leaf_dir / marker).exists():
            return marker
    return None


def run_make(make_target: str, size: int, timeout: int) -> tuple[int | None, str, bool]:
    """Run `make <make_target> SIZE=<size>`, killing the whole process group if
    it exceeds `timeout` (a defensive external cap -- see subprocess_timeout_for).

    task_bitwuzla/task_btor don't need to be waited out here: the .sby.in
    templates' `[cancelledby]` section makes SBY itself skip them (CANCELLED)
    once both prove-mode tasks are done, since `--sequential` runs
    task_abc/task_aiger first.

    Returns (returncode, stdout, timed_out).
    """
    cmd = ["make", "-C", str(XORGRID_DIR), f"SIZE={size}", make_target]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, _ = proc.communicate(timeout=timeout)
        return proc.returncode, stdout, False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, _ = proc.communicate()
        return None, stdout, True


def run_point(target: str, flavor: str, size: int) -> dict:
    spec = TARGETS[target]
    make_target = spec["make"] + ("-orfs" if flavor == "orfs" else "")
    timeout = subprocess_timeout_for(target, flavor)
    combo = f"S{size}"

    start = time.monotonic()
    returncode, stdout, timed_out = run_make(make_target, size, timeout)
    wall = round(time.monotonic() - start, 1)

    statuses: dict[str, str | None] = {}
    if spec["tasks"] is None:
        leaf_dir = RUN_DIR / f"check_{combo}_{flavor}_{spec['leaf']}"
        statuses["_"] = read_marker_status(leaf_dir)
    else:
        for task in spec["tasks"]:
            leaf_dir = RUN_DIR / f"check_{combo}_{flavor}_{spec['leaf']}_{task}"
            statuses[task] = read_marker_status(leaf_dir)

    alarm = any(s == "FAIL" for s in statuses.values())
    solved = (not alarm) and any(s == "PASS" for s in statuses.values())
    no_marker_at_all = all(s is None for s in statuses.values())

    return {
        "target": target,
        "flavor": flavor,
        "size": size,
        "solved": solved,
        "alarm": alarm,
        "statuses": statuses,
        "wall_seconds": wall,
        "make_returncode": returncode,
        "make_timed_out": timed_out,
        "build_error": no_marker_at_all and not timed_out,
        "log_tail": stdout[-2000:] if (alarm or timed_out or no_marker_at_all) else None,
        "timestamp": time.time(),
    }


class SweepLog:
    def __init__(self, path: Path):
        self.path = path
        self.records: list[dict] = []
        self.cache: dict[tuple[str, str, int], dict] = {}
        if path.exists():
            with open(path) as f:
                self.records = json.load(f)
            for r in self.records:
                self.cache[(r["target"], r["flavor"], r["size"])] = r

    def get_cached(self, target: str, flavor: str, size: int) -> dict | None:
        r = self.cache.get((target, flavor, size))
        if r is None:
            return None
        # Only reuse definitive outcomes -- re-run anything ambiguous.
        if r["build_error"] or r["make_timed_out"]:
            return None
        return r

    def append(self, record: dict) -> None:
        self.records.append(record)
        self.cache[(record["target"], record["flavor"], record["size"])] = record
        self._flush()

    def _flush(self) -> None:
        tmp = self.path.with_suffix(".json.tmp")
        with open(tmp, "w") as f:
            json.dump(self.records, f, indent=2)
        os.replace(tmp, self.path)


def get_or_run(target: str, flavor: str, size: int, log: SweepLog, refresh: bool) -> dict:
    if not refresh:
        cached = log.get_cached(target, flavor, size)
        if cached is not None:
            print(f"  SIZE={size}: cached -> solved={cached['solved']} alarm={cached['alarm']}")
            return cached
    print(f"  SIZE={size}: running (timeout={subprocess_timeout_for(target, flavor)}s)...", flush=True)
    result = run_point(target, flavor, size)
    log.append(result)
    tag = "ALARM" if result["alarm"] else ("solved" if result["solved"] else "not solved")
    print(
        f"    -> {tag} statuses={result['statuses']} "
        f"wall={result['wall_seconds']}s timed_out={result['make_timed_out']}"
    )
    return result


def search_frontier(
    target: str, flavor: str, start_size: int, resolution: int, log: SweepLog, refresh: bool
) -> dict:
    size = start_size
    last_solved = None
    first_unsolved = None
    alarm_result = None

    while True:
        result = get_or_run(target, flavor, size, log, refresh)
        if result["alarm"]:
            alarm_result = result
            break
        if result["solved"]:
            last_solved = size
            size *= 2
        else:
            first_unsolved = size
            break

    if alarm_result is not None:
        return {"status": "ALARM", "size": None, "detail": alarm_result}

    if last_solved is None:
        return {"status": "NONE_SOLVED", "size": None, "first_unsolved": first_unsolved}

    lo, hi = last_solved, first_unsolved
    while hi - lo > resolution:
        mid = lo + (hi - lo) // 2
        if mid == lo:
            break
        result = get_or_run(target, flavor, mid, log, refresh)
        if result["alarm"]:
            return {"status": "ALARM", "size": None, "detail": result}
        if result["solved"]:
            lo = mid
        else:
            hi = mid

    return {"status": "RESOLVED", "size": lo, "bracket": [lo, hi]}


def load_frontier() -> dict:
    if FRONTIER_PATH.exists():
        with open(FRONTIER_PATH) as f:
            return json.load(f)
    return {}


def save_frontier(frontier: dict) -> None:
    tmp = FRONTIER_PATH.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(frontier, f, indent=2)
    os.replace(tmp, FRONTIER_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flavor", choices=["yosys", "orfs"], required=True)
    parser.add_argument(
        "--targets",
        default=",".join(TARGETS),
        help=f"comma-separated subset of {{{','.join(TARGETS)}}}",
    )
    parser.add_argument("--start-size", type=int, default=4)
    parser.add_argument("--resolution", type=int, default=4)
    parser.add_argument(
        "--seed-from-yosys",
        action="store_true",
        help="for --flavor orfs, start each target's search at its already-known "
        "yosys frontier (from results/frontier.json) instead of --start-size",
    )
    parser.add_argument(
        "--refresh", action="store_true", help="ignore cached sweep_log.json entries"
    )
    args = parser.parse_args()

    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    for t in targets:
        if t not in TARGETS:
            parser.error(f"unknown target {t!r}; choose from {list(TARGETS)}")

    if args.start_size * args.start_size * FIXED_F < FIXED_I:
        parser.error(
            f"--start-size {args.start_size} violates gen_xorgrid.py's "
            f"I <= SIZE*SIZE*F constraint (I={FIXED_I}, F={FIXED_F})"
        )

    if args.flavor == "orfs" and not (XORGRID_DIR / ".." / "orfs" / "flow").is_dir():
        parser.error(
            "No OpenROAD-flow-scripts checkout found at ../orfs. "
            "Run 'make orfs' from the repo root first."
        )

    RESULTS_DIR.mkdir(exist_ok=True)
    log = SweepLog(SWEEP_LOG_PATH)
    frontier = load_frontier()

    for target in targets:
        start_size = args.start_size
        if args.flavor == "orfs" and args.seed_from_yosys:
            seeded = frontier.get(target, {}).get("yosys")
            if isinstance(seeded, int):
                start_size = max(args.start_size, seeded)

        print(f"=== {target} / {args.flavor} (start_size={start_size}) ===")
        outcome = search_frontier(target, args.flavor, start_size, args.resolution, log, args.refresh)

        frontier.setdefault(target, {})
        if outcome["status"] == "RESOLVED":
            frontier[target][args.flavor] = outcome["size"]
            print(f"  frontier: SIZE={outcome['size']} (bracket {outcome['bracket']})")
        elif outcome["status"] == "NONE_SOLVED":
            frontier[target][args.flavor] = None
            print(f"  frontier: none solved (first unsolved SIZE={outcome['first_unsolved']})")
        else:  # ALARM
            frontier[target][args.flavor] = "ALARM"
            print(f"  ALARM: genuine FAIL at SIZE={outcome['detail']['size']} -- stopping this target/flavor")
            print(f"  statuses: {outcome['detail']['statuses']}")

        save_frontier(frontier)

    print()
    print(f"Wrote {SWEEP_LOG_PATH}")
    print(f"Wrote {FRONTIER_PATH}")


if __name__ == "__main__":
    main()
