import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import checks
import design as dl
import flow
import kpi
import runner

REPO = HERE.parent
FIELDS = [
    "experiment",
    "design",
    "axis",
    "point",
    "flavor",
    "check",
    "engine",
    "variant",
    "result",
    "reason",
    "secs",
    "limit",
    "s",
    "reset_assumed",
    "power_up",
    "miter",
    "tools",
    "versions",
    "input_hash",
    "check_hash",
    "source",
    "workdir",
]
CHECKS = {
    "eqy": lambda b, o, lim, a, v, d: checks.run_eqy(b, o, lim, a.jobs, a.mem_cap, v),
    "sby_mi": lambda b, o, lim, a, v, d: checks.run_sby_mi(b, o, lim, a.mem_cap, v),
    "cover": lambda b, o, lim, a, v, d: checks.run_cover(
        b, o, lim, a.mem_cap, v, **d["cover"]
    ),
}
MUTANT_CHECKS = (
    "sby_mi",
    "eqy",
)
MUTANT_MAX_SECS = 60
STOP_AFTER = 2
KEY = (
    "design",
    "axis",
    "point",
    "flavor",
    "check",
    "variant",
    "tools",
    "versions",
    "input_hash",
    "limit",
)


def versions():
    out = []
    for cmd in (["eqy", "--version"], ["sby", "--version"], ["yosys", "-V"]):
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, check=False)
            out.append((p.stdout or p.stderr).strip().split("\n")[0])
        except FileNotFoundError:
            out.append(f"{cmd[0]}: not found")
    return "; ".join(out)


def design_file(arg):
    p = Path(arg)
    return (
        p / "design.toml"
        if p.is_dir()
        else p
        if p.suffix == ".toml"
        else HERE / "designs" / arg / "design.toml"
    )


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("designs", nargs="+")
    ap.add_argument(
        "--ladders",
        action="store_true",
        help="run the design's [[ladders]] instead of its table",
    )
    ap.add_argument(
        "--point", action="append", help="only this point (e.g. Width_g=8); repeatable"
    )
    ap.add_argument(
        "--flavors",
        default=",".join(dl.FLAVORS),
        help="gate flows (a design's disabled ones are skipped)",
    )
    ap.add_argument("--checks", default="eqy,sby_mi,cover,mutants")
    ap.add_argument(
        "--tools",
        action="append",
        help="NAME=BINDIR; repeatable (default: PATH as it is)",
    )
    ap.add_argument(
        "--timeout",
        type=int,
        help="limit per check (default: the design's or the ladder's timeout)",
    )
    ap.add_argument("--experiment", default="table")
    ap.add_argument("--jobs", type=int, default=8, help="eqy -j")
    ap.add_argument("--mem-cap", default="16G")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    checks_wanted, flavors = args.checks.split(","), args.flavors.split(",")
    if unknown := set(checks_wanted) - {*CHECKS, "mutants"}:
        sys.exit(f"unknown checks {sorted(unknown)} ({', '.join(CHECKS)}, mutants)")
    if unknown := set(flavors) - set(dl.FLAVORS):
        sys.exit(f"unknown flavors {sorted(unknown)} ({', '.join(dl.FLAVORS)})")
    scored = [c for c in checks_wanted if c in kpi.SCORED]
    tools = (
        [tuple(t.split("=", 1)) for t in args.tools]
        if args.tools
        else [("default", "")]
    )
    base_path = os.environ["PATH"]
    ver = {}
    for tname, bindir in tools:
        os.environ["PATH"] = f"{bindir}{os.pathsep}{base_path}" if bindir else base_path
        ver[tname] = versions()
    os.environ["PATH"] = base_path
    runner.become_subreaper()
    if args.mem_cap:
        runner.setup_mem_cap(args.mem_cap)
    out = HERE / "results" / args.experiment / "results.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if out.exists():
        with open(out, newline="") as fh:
            r = csv.DictReader(fh)
            rows = list(r)
        if r.fieldnames != FIELDS:
            if not set(r.fieldnames) < set(FIELDS):
                sys.exit(
                    f"{out} has other columns than this version writes; use a new --experiment"
                )
            kpi.update(out, FIELDS)
            rows = [{**dict.fromkeys(FIELDS, ""), **r} for r in rows]

    def key(r):
        return tuple(str(r[k]) for k in KEY)

    done = set() if args.force else {key(r) for r in rows}
    seen = {(key(r), r["result"], r["reason"]) for r in rows}

    def note(row):
        r = {k: str(row.get(k, "")) for k in FIELDS}
        if (key(r), r["result"], r["reason"]) not in seen:
            emit(row)

    def emit(row):
        new = not out.exists()
        with open(out, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow({k: row.get(k, "") for k in FIELDS})
        rows.append({k: str(row.get(k, "")) for k in FIELDS})
        done.add(key(rows[-1]))
        seen.add((key(rows[-1]), rows[-1]["result"], rows[-1]["reason"]))
        print(
            f"{row['design']:14s} {row.get('axis', '')[:12]:12s} {row['point']:22s} {row.get('flavor', ''):5s} "
            f"{row['variant']:4s} {row['tools']:8s} {row['check']:7s} {row.get('engine', ''):8s} "
            f"{row['result']:8s} {row.get('secs', '')!s:>7}s  {str(row.get('reason', ''))[:90]}",
            flush=True,
        )

    def use(tname):
        bindir = dict(tools)[tname]
        os.environ["PATH"] = f"{bindir}{os.pathsep}{base_path}" if bindir else base_path

    def run(bdir, d, s, pname, tname, checks_):
        case = json.loads((bdir / "case.json").read_text())
        variant = case.get("variant", "orig")
        row0 = {
            **s["base"],
            "point": pname,
            "variant": variant,
            "tools": tname,
            "versions": ver[tname],
            "input_hash": case["input_hash"],
            "power_up": case["power_up"]["gate"],
        }
        use(tname)
        wdir = (
            HERE
            / "work"
            / args.experiment
            / d["name"]
            / f"{pname}_{case['flavor']}"
            / tname
            / s["wsub"]
        )
        for check in checks_:
            if key({**row0, "check": check}) not in done:
                for r in CHECKS[check](
                    bdir,
                    wdir / (check if variant == "orig" else f"{variant}/{check}"),
                    s["limit"],
                    args,
                    ver[tname],
                    d,
                ):
                    emit(
                        {
                            **row0,
                            "check": check,
                            **r,
                            "workdir": os.path.relpath(r["workdir"], REPO),
                        }
                    )
        os.environ["PATH"] = base_path

    def mine(bdir, tname, s, check_in):
        h = json.loads((bdir / "case.json").read_text())["input_hash"]
        return [
            r
            for r in rows
            if r["variant"] == "orig"
            and r["check"] in check_in
            and r["input_hash"] == h
            and r["tools"] == tname
            and r["axis"] == s["base"]["axis"]
            and r["limit"] == str(s["limit"])
        ]

    def passed(bdir, tname, s, max_secs=float("inf")):
        return any(
            r["result"] == "PASS" and float(r["secs"]) <= max_secs
            for r in mine(bdir, tname, s, MUTANT_CHECKS)
        )

    def solved(bdir, tname, s, check):
        covered = {
            r["input_hash"]
            for r in rows
            if r["check"] == "cover" and r["result"] == "COVERED"
        }
        confirmed = {
            r["input_hash"]
            for r in rows
            if r["check"] == "sby_mi" and r["result"] == "FAIL"
        }
        return any(
            kpi.s_of(r, covered, confirmed) < 2 for r in mine(bdir, tname, s, (check,))
        )

    def known_different(mb):
        h, orig = (
            json.loads((b / "case.json").read_text())["input_hash"]
            for b in (mb, mb.parent.parent)
        )
        sby = {(r["input_hash"], r["result"]) for r in rows if r["check"] == "sby_mi"}
        return (h, "FAIL") in sby and (orig, "PASS") in sby

    def mutant_dirs(bdir, s, pname):
        try:
            return checks.mutants(bdir)
        except checks.CheckError as e:
            note(
                {
                    **s["base"],
                    "point": pname,
                    "check": "mutate",
                    "variant": "-",
                    "result": "ERROR",
                    "reason": str(e),
                    "tools": "-",
                }
            )
            return []

    def series(d, flavor):
        base = {
            "experiment": args.experiment,
            "design": d["name"],
            "flavor": flavor,
            "source": "native",
        }
        if not args.ladders:
            return [
                {
                    "base": {**base, "axis": ""},
                    "points": dl.points(d),
                    "stop": False,
                    "wsub": "",
                    "limit": args.timeout or d["limits"]["timeout"],
                }
            ]
        return [
            {
                "base": {**base, "axis": lad["name"]},
                "points": lad["points"],
                "stop": True,
                "wsub": "ladder_" + re.sub(r"\W+", "_", lad["name"]),
                "limit": args.timeout or lad["timeout"],
            }
            for lad in d["ladders"]
        ]

    for name in args.designs:
        d = dl.load(design_file(name))
        for flavor in [f for f in flavors if d["flows"][f]["enabled"]]:
            for s in series(d, flavor):
                s["base"]["limit"] = s["limit"]
                built, unsolved = (
                    [],
                    defaultdict(int),
                )
                for point in s["points"]:
                    pname = dl.point_name(point)
                    if args.point and pname not in args.point:
                        continue
                    stopped = {
                        (t, c)
                        for t, _ in tools
                        for c in scored
                        if unsolved[(t, c)] >= STOP_AFTER
                    }
                    for t, c in sorted(stopped):
                        note(
                            {
                                **s["base"],
                                "point": pname,
                                "check": c,
                                "engine": "-",
                                "variant": "orig",
                                "result": "NOT_RUN",
                                "reason": f"stop rule: {STOP_AFTER} unsolved sizes in a row",
                                "tools": t,
                                "versions": ver[t],
                            }
                        )
                    if (
                        s["stop"]
                        and scored
                        and len(stopped) == len(tools) * len(scored)
                    ):
                        continue
                    try:
                        bdir = flow.build(
                            d, point, flavor, HERE / "build", args.rebuild
                        )
                    except flow.Unsupported as e:
                        note(
                            {
                                **s["base"],
                                "point": pname,
                                "check": "build",
                                "variant": "orig",
                                "result": "UNSUPPORTED",
                                "reason": str(e),
                                "tools": "-",
                            }
                        )
                        continue
                    except RuntimeError as e:
                        note(
                            {
                                **s["base"],
                                "point": pname,
                                "check": "build",
                                "variant": "orig",
                                "result": "ERROR",
                                "reason": str(e),
                                "tools": "-",
                            }
                        )
                        continue
                    built.append((pname, bdir))
                    for tname, _ in tools:
                        live = [
                            c
                            for c in checks_wanted
                            if c != "mutants" and (tname, c) not in stopped
                        ]
                        if scored and all((tname, c) in stopped for c in scored):
                            live = []
                        run(bdir, d, s, pname, tname, live)
                        if s["stop"]:
                            for c in set(scored) & set(live):
                                unsolved[(tname, c)] = (
                                    0
                                    if solved(bdir, tname, s, c)
                                    else unsolved[(tname, c)] + 1
                                )
                        if "mutants" in checks_wanted and passed(bdir, tname, s):
                            for mb in mutant_dirs(bdir, s, pname):
                                run(mb, d, s, pname, tname, MUTANT_CHECKS)
                                if known_different(mb):
                                    break
                for tname, _ in tools if "mutants" in checks_wanted else []:
                    fast = [
                        (checks.gate_cells(b), pname, b)
                        for pname, b in built
                        if passed(b, tname, s, MUTANT_MAX_SECS)
                    ]
                    if fast:
                        _, pname, b = max(fast)
                        for mb in mutant_dirs(b, s, pname):
                            run(mb, d, s, pname, tname, MUTANT_CHECKS)
    if out.exists():
        for r in kpi.update(out, FIELDS):
            if r["group"] in ("S_time", "S_size", "S"):
                print(
                    f"KPI {r['check']:7s} {r['tools']:10s} {r['group']:6s} {r['S']!s:7s} "
                    f"({r['solved']}/{r['instances']} solved); gate {r['gate']}"
                )


if __name__ == "__main__":
    try:
        main()
    finally:
        runner.reap_leftovers()
