# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "matplotlib>=3.11.1",
#     "polars>=1.43.2",
# ]
# ///
import argparse
import json
import sys
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common.bench import SHARED_TASKS_SBY, tasks_in
from _common.plots import generate_cross_benchmark_plots
from _common.results_cache import RESULT_COLUMNS, split_task_dir_name

NON_BENCHMARK_DIRS = {"_common", "sky130", "orfs", "summary"}


def active_tasks() -> set[str]:
    return tasks_in(SHARED_TASKS_SBY.read_text())


def filter_to_active_tasks(results: pl.DataFrame) -> pl.DataFrame:
    active = active_tasks()
    present = set(results["task"].unique().to_list())
    dropped = sorted(present - active)
    if dropped:
        print(
            f"excluding tasks commented out in {SHARED_TASKS_SBY.name}: "
            f"{', '.join(dropped)}"
        )
    filtered = results.filter(pl.col("task").is_in(active))
    if filtered.is_empty():
        raise SystemExit(
            f"no results left after filtering to the active tasks in "
            f"{SHARED_TASKS_SBY.name} ({', '.join(sorted(active)) or 'none'})"
        )
    return filtered


def _load_partial_from_cache(bench_dir: Path) -> pl.DataFrame | None:
    cache_path = bench_dir / "run" / "results_cache.json"
    if not cache_path.exists():
        return None
    try:
        cache = json.loads(cache_path.read_text())
    except json.JSONDecodeError:
        return None
    if not cache:
        return None

    rows: dict[tuple[str, str], dict] = {}
    for export_dir_name, entry in cache.items():
        is_orfs = export_dir_name.startswith("orfs_")
        placeholder_benchmark = "(in progress) (ORFS)" if is_orfs else "(in progress)"
        for task_key, row in entry.get("tasks", {}).items():
            split = split_task_dir_name(task_key)
            if split is None:
                continue
            task, sby_file = split
            variant = (
                "internal_asserts" if sby_file == "miter_extra_asserts.sby" else "miter"
            )
            key = (export_dir_name, task)
            out = rows.setdefault(
                key,
                {
                    "name": export_dir_name,
                    "task": task,
                    "benchmark": placeholder_benchmark,
                    **{f"{c}_miter": None for c in RESULT_COLUMNS},
                    **{f"{c}_internal_asserts": None for c in RESULT_COLUMNS},
                },
            )
            for c in RESULT_COLUMNS:
                out[f"{c}_{variant}"] = row.get(c)

    if not rows:
        return None
    return pl.DataFrame(list(rows.values()))


def collect_results(root: Path) -> pl.DataFrame:
    frames = []
    partial = []
    skipped = []
    for bench_dir in sorted(root.iterdir()):
        if not bench_dir.is_dir() or bench_dir.name in NON_BENCHMARK_DIRS:
            continue
        if bench_dir.name.startswith("."):
            continue

        results_path = bench_dir / "run" / "results.parquet"
        if results_path.exists():
            df = pl.read_parquet(results_path)
            frames.append(
                df.with_columns(pl.lit(bench_dir.name).alias("benchmark_dir"))
            )
            continue

        cache_df = _load_partial_from_cache(bench_dir)
        if cache_df is not None:
            partial.append(bench_dir.name)
            frames.append(
                cache_df.with_columns(pl.lit(bench_dir.name).alias("benchmark_dir"))
            )
            continue

        skipped.append(bench_dir.name)

    if partial:
        print(
            f"partial (still sweeping, from results_cache.json): {', '.join(partial)}"
        )
    if skipped:
        print(f"skipping (nothing finished yet): {', '.join(skipped)}")
    if not frames:
        raise SystemExit(
            "no benchmark directory has any results yet -- run "
            "find_max_parameter.py in at least one first"
        )
    return pl.concat(frames, how="diagonal_relaxed")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output directory (default: <frontier_checks_root>/summary)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    out_dir = args.out or (root / "summary")
    out_dir.mkdir(parents=True, exist_ok=True)

    results = filter_to_active_tasks(collect_results(root))
    results.write_parquet(out_dir / "results.parquet")
    results.write_csv(out_dir / "results.csv")
    n_benchmarks = results["benchmark_dir"].n_unique()
    print(
        f"Wrote combined results ({results.height} rows across "
        f"{n_benchmarks} benchmarks) to {out_dir}"
    )

    plot_paths = generate_cross_benchmark_plots(results, out_dir / "plots")
    print(f"Wrote {len(plot_paths)} cross-benchmark plots to {out_dir / 'plots'}")


if __name__ == "__main__":
    main()
