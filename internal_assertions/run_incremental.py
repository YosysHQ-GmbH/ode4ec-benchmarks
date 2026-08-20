import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import report

TARGETS = [
    "sby",
    "sby-orfs",
    # "eqy",
    # "eqy-orfs",
    "synth",
    "openroad-synth",
    "custom-miter",
    "custom-miter-orfs",
    "custom-miter-extra-asserts",
    "custom-miter-extra-asserts-orfs",
    "mutation-check",
    "mutation-check-orfs",
    "mutation-check-extra-asserts",
    "mutation-check-extra-asserts-orfs",
    "custom-miter-extra-asserts-mutation",
    "custom-miter-extra-asserts-mutation-orfs",
]

DEFAULT_PLATFORM = "sky130hd"
ORFS_RESULT_SUBDIRS = ("results", "logs", "objects", "reports")

TOP_MODULE_RE = re.compile(r"^export\s+TOP_MODULE\s*=\s*(\S+)", re.MULTILINE)
PLATFORM_RE = re.compile(r"^export\s+PLATFORM\s*=\s*(\S+)", re.MULTILINE)


def is_orfs_target(target: str) -> bool:
    return target.endswith("-orfs") or target == "openroad-synth"


def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def target_defined(makefile_text: str, target: str) -> bool:
    return re.search(rf"^{re.escape(target)}:", makefile_text, re.MULTILINE) is not None


def discover_leaves(root: str) -> list[tuple[str, str, str]]:
    leaves: list[tuple[str, str, str]] = []

    def walk(dir_path: str, benchmark_id: str) -> None:
        makefile_path = os.path.join(dir_path, "Makefile")
        if not os.path.isfile(makefile_path):
            return
        with open(makefile_path) as f:
            text = f.read()
        if "define TARGET_RULE" in text:
            children = sorted(
                d
                for d in os.listdir(dir_path)
                if os.path.isdir(os.path.join(dir_path, d))
                and os.path.isfile(os.path.join(dir_path, d, "Makefile"))
            )
            for child in children:
                walk(os.path.join(dir_path, child), f"{benchmark_id}/{child}")
        else:
            leaves.append((benchmark_id, dir_path, text))

    top_dirs = sorted(
        d
        for d in os.listdir(root)
        if d not in report.IGNORED_DIRS
        and os.path.isdir(os.path.join(root, d))
        and os.path.isfile(os.path.join(root, d, "Makefile"))
    )
    for d in top_dirs:
        walk(os.path.join(root, d), d)
    return leaves


def applicable_targets(makefile_text: str, yosys_only: bool) -> list[str]:
    targets = [t for t in TARGETS if target_defined(makefile_text, t)]
    if yosys_only:
        targets = [t for t in targets if not is_orfs_target(t)]
    return targets


def extract_var(
    makefile_text: str, pattern: re.Pattern, default: str | None
) -> str | None:
    matches = pattern.findall(makefile_text)
    return matches[-1] if matches else default


def load_report(path: str) -> dict:
    if not os.path.exists(path):
        return {"generated_at": None, "progress": {}, "cleaned": {}, "results": {}}
    with open(path) as f:
        data = json.load(f)
    data.setdefault("progress", {})
    data.setdefault("cleaned", {})
    data.setdefault("results", {})
    return data


def save_report(path: str, data: dict) -> None:
    data["generated_at"] = now_iso()
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.replace(tmp_path, path)


def cleanup_leaf(
    root: str, leaf_dir: str, applicable: list[str], makefile_text: str
) -> None:
    for rel in ("run", "internal_asserts", os.path.join("openroad", "run")):
        p = os.path.join(leaf_dir, rel)
        if os.path.isdir(p):
            shutil.rmtree(p)

    if not any(is_orfs_target(t) for t in applicable):
        return

    top_module = extract_var(makefile_text, TOP_MODULE_RE, None)
    if not top_module:
        return
    platform = extract_var(makefile_text, PLATFORM_RE, DEFAULT_PLATFORM)

    for sub in ORFS_RESULT_SUBDIRS:
        base = os.path.join(root, "orfs", "flow", sub, platform)
        if not os.path.isdir(base):
            continue
        for entry in os.listdir(base):
            if entry == top_module or entry.startswith(top_module + "_"):
                shutil.rmtree(os.path.join(base, entry), ignore_errors=True)


def ensure_orfs_checkout(root: str) -> None:
    orfs_git = os.path.join(root, "orfs", ".git")
    if os.path.isdir(orfs_git):
        return
    print("Fetching OpenROAD-flow-scripts (make orfs)...")
    subprocess.run(["make", "-C", root, "orfs"], check=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Incrementally run benchmark checks, checkpointing to report.json "
        "so an interrupted run can resume without redoing finished work, and cleaning "
        "up each benchmark's build artifacts once its results are captured."
    )
    parser.add_argument(
        "--root", default=".", help="internal_assertions root (default: .)"
    )
    parser.add_argument("--report", default="report.json", help="report file path")
    parser.add_argument(
        "--yosys-only",
        action="store_true",
        help="skip -orfs targets and openroad-synth",
    )
    parser.add_argument(
        "--leaf",
        action="append",
        dest="leaves",
        help="restrict to this benchmark id (repeatable), e.g. --leaf serv",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="skip cleanup of run/ dirs after a benchmark finishes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the (benchmark, target) plan without executing anything",
    )
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    report_path = os.path.join(root, args.report)

    leaves = discover_leaves(root)
    if args.leaves:
        wanted = set(args.leaves)
        leaves = [l for l in leaves if l[0] in wanted]
        missing = wanted - {l[0] for l in leaves}
        if missing:
            print(f"Warning: no such benchmark(s): {', '.join(sorted(missing))}")

    if not args.dry_run and not args.yosys_only:
        any_orfs = any(
            is_orfs_target(t)
            for _, _, text in leaves
            for t in applicable_targets(text, yosys_only=False)
        )
        if any_orfs:
            ensure_orfs_checkout(root)

    data = load_report(report_path)
    progress = data["progress"]
    cleaned = data["cleaned"]
    results = data["results"]

    if args.dry_run:
        for benchmark_id, _leaf_dir, text in leaves:
            applicable = applicable_targets(text, args.yosys_only)
            done = set(progress.get(benchmark_id, {}))
            for target in applicable:
                state = "done" if target in done else "TODO"
                print(f"{benchmark_id:32} {target:40} {state}")
        return

    total_leaves = len(leaves)
    for idx, (benchmark_id, leaf_dir, text) in enumerate(leaves, start=1):
        applicable = applicable_targets(text, args.yosys_only)
        if not applicable:
            continue

        leaf_progress = progress.setdefault(benchmark_id, {})
        remaining = [t for t in applicable if t not in leaf_progress]

        if remaining:
            print(
                f"[{idx}/{total_leaves}] {benchmark_id}: {len(remaining)} target(s) to run"
            )

        for target in remaining:
            print(f"  -> make -C {leaf_dir} {target}")
            start = time.time()
            proc = subprocess.run(["make", "-C", leaf_dir, target])
            elapsed = time.time() - start
            leaf_progress[target] = {
                "returncode": proc.returncode,
                "elapsed_seconds": round(elapsed, 1),
                "finished_at": now_iso(),
            }

            run_dir = os.path.join(leaf_dir, "run")
            if os.path.isdir(run_dir):
                results[benchmark_id] = report.build_benchmark_results(
                    benchmark_id, run_dir
                )

            save_report(report_path, data)
            status = "ok" if proc.returncode == 0 else f"exit {proc.returncode}"
            print(f"     {target}: {status} ({elapsed:.1f}s)")

        if (
            not args.no_clean
            and not cleaned.get(benchmark_id)
            and set(applicable) <= set(leaf_progress)
        ):
            cleanup_leaf(root, leaf_dir, applicable, text)
            cleaned[benchmark_id] = True
            save_report(report_path, data)

    done_leaves = sum(
        1
        for benchmark_id, _leaf_dir, text in leaves
        if applicable_targets(text, args.yosys_only)
        and set(applicable_targets(text, args.yosys_only))
        <= set(progress.get(benchmark_id, {}))
    )
    print(
        f"Done: {done_leaves}/{total_leaves} benchmarks fully attempted. Report: {report_path}"
    )


if __name__ == "__main__":
    main()
