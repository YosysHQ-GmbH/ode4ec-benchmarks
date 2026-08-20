import argparse
import json
import os
import re
from enum import Enum

IGNORED_DIRS = {"fifo", "orfs", "sky130", "sort", "reduction_trees"}

MARKER_FILES = ["PASS", "FAIL", "UNKNOWN", "ERROR", "TIMEOUT", "CANCELLED"]

CLOCK_TIME_PATTERN = re.compile(
    r"^Elapsed clock time \[H:MM:SS \(secs\)\]: (\d+:\d+:\d+) \((\d+)\)$",
    flags=re.MULTILINE,
)
PROCESS_TIME_PATTERN = re.compile(
    r"^Elapsed process time \[H:MM:SS \(secs\)\]: (\d+:\d+:\d+) \((\d+)\)$",
    flags=re.MULTILINE,
)

FLAVORS = ["yosys", "orfs"]

COLUMNS = [
    "eqy",
    "sby",
    "miter",
    "miter-extra-asserts",
    "mutation",
    "mutation-custom-miter",
]

NO_COMBO = "null"


class RunStatus(str, Enum):
    DNF = "DNF"
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"
    TIMEOUT = "TIMEOUT"
    CANCELLED = "CANCELLED"


STATUS_ORDER = [
    RunStatus.PASS,
    RunStatus.FAIL,
    RunStatus.TIMEOUT,
    RunStatus.ERROR,
    RunStatus.UNKNOWN,
    RunStatus.CANCELLED,
    RunStatus.DNF,
]

MUTATION_COLUMNS = {"mutation", "mutation-custom-miter"}

MUTATION_LABELS = {
    RunStatus.PASS: "NOT_CAUGHT",
    RunStatus.FAIL: "CAUGHT",
}

CHECKTYPE_RULES = [
    ("mutation_check_with_extra_asserts", "mutation-custom-miter"),
    ("mutation_check_extra_asserts", "mutation-custom-miter"),
    ("mutation_check", "mutation"),
    ("custom_miter_with_extra_asserts", "miter-extra-asserts"),
    ("custom_miter_extra_asserts", "miter-extra-asserts"),
    ("custom_miter", "miter"),
    ("eqy", "eqy"),
    ("sby", "sby"),
]


def classify_checktype(checktype: str) -> str | None:
    for token, column in CHECKTYPE_RULES:
        if checktype == token:
            return column
    return None


def parse_status_file(path: str) -> dict:
    result = {
        "elapsed_clock_time": None,
        "elapsed_clock_seconds": None,
        "elapsed_process_time": None,
        "elapsed_process_seconds": None,
    }
    with open(path) as f:
        content = f.read()
    match = CLOCK_TIME_PATTERN.search(content)
    if match:
        result["elapsed_clock_time"] = match.group(1)
        result["elapsed_clock_seconds"] = int(match.group(2))
    match = PROCESS_TIME_PATTERN.search(content)
    if match:
        result["elapsed_process_time"] = match.group(1)
        result["elapsed_process_seconds"] = int(match.group(2))
    return result


def read_leaf_status(leaf_dir: str) -> dict:
    for marker in MARKER_FILES:
        marker_path = os.path.join(leaf_dir, marker)
        if os.path.exists(marker_path):
            info = parse_status_file(marker_path)
            info["status"] = RunStatus(marker)
            return info
    return {
        "status": RunStatus.DNF,
        "elapsed_clock_time": None,
        "elapsed_clock_seconds": None,
        "elapsed_process_time": None,
        "elapsed_process_seconds": None,
    }


def split_task_suffix(name: str) -> tuple[str, str | None]:
    match = re.search(r"^(.*)_task_(.+)$", name)
    if match:
        return match.group(1), match.group(2)
    return name, None


def parse_base(
    benchmark_id: str, base: str
) -> tuple[str | None, str | None, str | None]:
    family = benchmark_id.split("/")[0]
    is_combo_family = family.startswith("ol_")

    if is_combo_family:
        if not base.startswith("check_"):
            return None, None, None
        rest = base[len("check_") :]
        anchor = None
        for flavor in FLAVORS:
            token = f"_{flavor}_"
            idx = rest.find(token)
            if idx != -1:
                anchor = (idx, flavor, token)
                break
        if anchor is None:
            return None, None, None
        idx, flavor, token = anchor
        combo = rest[:idx]
        checktype = rest[idx + len(token) :]
        column = classify_checktype(checktype)
        if column is None or not combo:
            return None, None, None
        return combo, flavor, column

    flavor = None
    for candidate in FLAVORS:
        suffix = f"_{candidate}"
        if base.endswith(suffix):
            flavor = candidate
            base_wo_flavor = base[: -len(suffix)]
            break
    if flavor is None:
        return None, None, None

    if base_wo_flavor.startswith("mutation_check"):
        checktype = base_wo_flavor
    elif base_wo_flavor.startswith("check_"):
        checktype = base_wo_flavor[len("check_") :]
    else:
        return None, None, None

    column = classify_checktype(checktype)
    if column is None:
        return None, None, None
    return None, flavor, column


def collect_leaves(run_dir: str) -> list[tuple[str, str | None]]:
    entries = sorted(
        e
        for e in os.listdir(run_dir)
        if (e.startswith("check_") or e.startswith("mutation_check_"))
        and os.path.isdir(os.path.join(run_dir, e))
    )

    leaves = []
    bases_with_tasks = set()
    for entry in entries:
        base, task = split_task_suffix(entry)
        if task is not None:
            leaves.append((entry, base, task))
            bases_with_tasks.add(base)

    for entry in entries:
        base, task = split_task_suffix(entry)
        if task is not None:
            continue
        if entry in bases_with_tasks:
            continue
        if any(os.path.exists(os.path.join(run_dir, entry, m)) for m in MARKER_FILES):
            leaves.append((entry, entry, None))

    return leaves


def rollup_cell(task_results: dict) -> dict:
    counts = {s: 0 for s in STATUS_ORDER}
    for info in task_results.values():
        counts[info["status"]] += 1

    non_dnf_statuses = {s for s in STATUS_ORDER if s != RunStatus.DNF and counts[s]}

    if not task_results or not non_dnf_statuses:
        status = "DNF"
    elif len(non_dnf_statuses) == 1 and counts[RunStatus.DNF] == 0:
        status = non_dnf_statuses.pop().value
    else:
        status = "MIXED"

    seconds = [
        info["elapsed_clock_seconds"]
        for info in task_results.values()
        if info["elapsed_clock_seconds"] is not None
    ]
    clock_seconds = max(seconds) if seconds else None

    cell = {
        "status": status,
        "clock_seconds": clock_seconds,
        "task_count": len(task_results),
        "counts": {s.value: c for s, c in counts.items() if c},
        "tasks": {
            (task if task is not None else "_"): {
                "status": info["status"],
                "elapsed_clock_time": info["elapsed_clock_time"],
                "elapsed_clock_seconds": info["elapsed_clock_seconds"],
                "elapsed_process_time": info["elapsed_process_time"],
                "elapsed_process_seconds": info["elapsed_process_seconds"],
            }
            for task, info in task_results.items()
        },
    }

    return cell


def add_verdict(column: str, cell: dict) -> dict:
    if column not in MUTATION_COLUMNS:
        return cell
    status = cell["status"]
    if status in ("DNF", "MIXED"):
        cell["verdict"] = status
    else:
        cell["verdict"] = MUTATION_LABELS.get(RunStatus(status), status)
    return cell


def build_benchmark_results(benchmark_id: str, run_dir: str) -> dict:
    leaves = collect_leaves(run_dir)

    grouped: dict[tuple[str, str, str], dict] = {}

    for entry, base, task in leaves:
        combo, flavor, column = parse_base(benchmark_id, base)
        if column is None:
            continue
        combo_key = combo if combo is not None else NO_COMBO
        key = (combo_key, flavor, column)
        leaf_dir = os.path.join(run_dir, entry)
        grouped.setdefault(key, {})[task if task is not None else "_"] = (
            read_leaf_status(leaf_dir)
        )

    result: dict = {}
    combos = sorted({k[0] for k in grouped}) or [NO_COMBO]
    for combo_key in combos:
        result[combo_key] = {}
        for flavor in FLAVORS:
            flavor_result = {}
            for column in COLUMNS:
                task_results = grouped.get((combo_key, flavor, column), {})
                cell = rollup_cell(task_results)
                cell = add_verdict(column, cell)
                flavor_result[column] = cell
            result[combo_key][flavor] = flavor_result

    return result


def format_cell(column: str, cell: dict) -> str:
    status = cell["status"]
    seconds = cell["clock_seconds"]
    if status == "DNF":
        return "-"
    if status == "MIXED":
        parts = []
        for s in STATUS_ORDER:
            count = cell["counts"].get(s.value, 0)
            if not count:
                continue
            label = MUTATION_LABELS.get(s, s.value) if column in MUTATION_COLUMNS else s.value
            parts.append(f"{count} {label}")
        label = " / ".join(parts)
    elif column in MUTATION_COLUMNS:
        label = cell["verdict"]
    else:
        label = status
    if seconds is None:
        return label
    return f"{label} {seconds}s"


def print_table(results: dict) -> None:
    rows: list[tuple[str, dict]] = []
    for benchmark_id in sorted(results):
        entry = results[benchmark_id]
        for combo_key in sorted(entry):
            for flavor in FLAVORS:
                flavor_result = entry[combo_key].get(flavor)
                if not flavor_result:
                    continue
                if all(c["status"] == "DNF" for c in flavor_result.values()):
                    continue
                row_name = (
                    f"{benchmark_id}[{combo_key}]-{flavor}"
                    if combo_key != NO_COMBO
                    else f"{benchmark_id}-{flavor}"
                )
                rows.append((row_name, flavor_result))

    if not rows:
        print("No results found.")
        return

    header = ["benchmark"] + COLUMNS
    table = [header]
    for row_name, flavor_result in rows:
        table.append([row_name] + [format_cell(c, flavor_result[c]) for c in COLUMNS])

    widths = [max(len(r[i]) for r in table) for i in range(len(header))]
    for row in table:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print the results already recorded in report.json as a table. "
        "Does not run or collect anything itself — run 'make run-incremental' first."
    )
    parser.add_argument("--report", default="report.json", help="path to report.json")
    args = parser.parse_args()

    if not os.path.exists(args.report):
        print(f"{args.report} not found. Run 'make run-incremental' first.")
        return

    with open(args.report) as f:
        data = json.load(f)

    print_table(data.get("results", {}))


if __name__ == "__main__":
    main()
