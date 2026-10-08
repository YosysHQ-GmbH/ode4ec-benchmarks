# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "matplotlib>=3.11.1",
#     "polars>=1.43.2",
# ]
# ///
"""Frontier search for seq_prove, eqy or plain sby on the scaling axes of internal_assertions_frontier_checks.

usage: uv run frontier.py SPEC [SPEC ...] --tag TAG [--tool seq_prove|eqy|sby] [--prove "--k 2 --chunk 16 --model"]
                          [--old-asserts B,...] [--build FLAG ...] [--engines E,...] [--orfs] [--mem-cap 16G]

SPEC is BENCH or BENCH:AXIS, where AXIS is part of the axis name (`ol_pl_stage:Stages`). The axes come from
each benchmark's find_max_parameter.py and are searched like the sby frontier: double, then bisect. A step
passes if the tool returns PASS within the axis' time limit. For seq_prove the model build counts, as sby's
prep counts in its timeout. ORFS axes need --orfs. --old-asserts lists benchmarks that keep the run's own
asserts.vh instead of regenerated candidates.

--tool eqy runs run_bench.run_eqy (bind *, sby abc pdr), variant "eqy".
--tool sby runs the plain miter (miter.sby, no internal asserts) without clk2fflogic, one search per
--engines task, variant "noclk2ff:ENGINE". clk2fflogic takes two steps per clock cycle where seq_prove and
eqy take one. Removing it is only sound for a single posedge clock, so each run first has to pass
seq_prove's guards on the plain design. The guard's time goes into build_secs, not total_secs.

Writes seqprove/runs/TAG/frontier.csv, one row per step. A rerun reuses rows with the same settings, so a
stopped search resumes. frontier_summary.csv compares the result with the best prove-mode engine of the sby
frontier (abc-pdr, aiger-suprove, aiger-rIC3) for MI and IA. bmc-mode PASSes are bounded and do not count.
"""
import argparse
import csv
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import build_model
import run_bench
from model import Model
from run_bench import FRONTIER, RUNS

PROVE_ENGINES = ("abc-pdr", "aiger-suprove", "aiger-rIC3")
NOCLK2FF = "miter_noclk2ff.sby"
GUARD_TIMEOUT = 1800
NOCLK2FF_NOTE = [
    "# clk2fflogic removed (written by seqprove/seqprove/frontier.py --tool sby from miter.sby): sby's default",
    "# flow (multiclock off: async2sync, formalff -clk2ff) then takes one step per clock cycle, as seq_prove's",
    "# model and eqy do. Only sound for a single posedge clock: the GUARD lines fail on negedge flip-flops,",
    "# tristates and latches, and frontier.py runs this file only if the design has exactly one clock net.",
]
FIELDS = ["bench", "axis", "n", "run", "cells", "timeout", "result", "reason", "build_secs", "prove_secs",
          "total_secs", "properties", "properties_proven", "candidates", "candidates_proven", "variant",
          "prove_args"]


def load_axes(bench):
    """The benchmark's axes, as its main() passes them to run_and_report. Changes the cwd."""
    bdir = FRONTIER / bench
    os.chdir(bdir)
    sys.path.insert(0, str(FRONTIER))
    spec = importlib.util.spec_from_file_location(f"find_max_parameter_{bench}", bdir / "find_max_parameter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    axes = []
    mod.run_and_report = lambda benchmarks, _run_dir: axes.extend(benchmarks)
    mod.main()
    return axes


def baseline(bench, axis):
    """{flavor: (cells, run, engine)}: the largest prove-mode PASS of the sby frontier."""
    best = {"MI": (0, "-", "-"), "IA": (0, "-", "-")}
    path = FRONTIER / bench / "run" / "results.csv"
    if not path.exists():
        return best
    with open(path) as fh:
        for r in csv.DictReader(fh):
            if r["benchmark"] != axis or r["task"] not in PROVE_ENGINES:
                continue
            for flavor, suf in (("MI", "miter"), ("IA", "internal_asserts")):
                cells = int(r.get(f"cells_{suf}") or 0)
                if r.get(f"result_{suf}") == "PASS" and cells > best[flavor][0]:
                    best[flavor] = (cells, r["name"], r["task"])
    return best


def noclk2ff_sby(text):
    """miter.sby without clk2fflogic, with build_model's guards before async2sync."""
    out, sec, removed, guarded = [], None, 0, False
    for ln in text.split("\n"):
        m = re.match(r"^\[(\w+)\]", ln)
        if m:
            sec = m.group(1)
        elif sec == "script" and re.match(r"\s*(~?\S+:\s*)?clk2fflogic\b", ln):
            out += NOCLK2FF_NOTE
            removed += 1
            continue
        elif sec == "script" and re.match(r"\s*async2sync\b", ln) and not guarded:
            out += build_model.guard_lines(build_model.GUARDS + [build_model.LATCH_GUARD])
            guarded = True
        out.append(ln)
    if not removed or not guarded:
        raise ValueError(f"miter.sby: {'no clk2fflogic' if not removed else 'no async2sync'} in [script]")
    return "\n".join(out)


class Search:
    def __init__(self, args):
        self.args = args
        self.tagdir = RUNS / args.tag
        self.tagdir.mkdir(parents=True, exist_ok=True)
        self.csv = self.tagdir / "frontier.csv"
        self.done, self.on_axis = {}, set()
        if self.csv.exists():
            with open(self.csv) as fh:
                for r in csv.DictReader(fh):
                    self.done[(r["bench"], r["run"], r["variant"], r["prove_args"])] = r
                    self.on_axis.add((r["bench"], r["axis"], r["run"], r["variant"]))

    def record(self, row):
        new = not self.csv.exists()
        with open(self.csv, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow(row)
        self.done[(row["bench"], row["run"], row["variant"], row["prove_args"])] = row
        self.on_axis.add((row["bench"], row["axis"], row["run"], row["variant"]))
        print(f"  {row['axis']:24s} n={row['n']:<6} {row['run']:40s} {row['result']:8s} "
              f"{row.get('total_secs', '-')!s:>7}s / {row.get('timeout', '-')}s  {row['reason']}", flush=True)

    def step(self, bench, axis, setup_gen, n, engine=None):
        """True if the tool passes size n within the axis' time limit."""
        a = self.args
        if a.tool == "eqy":
            variant, settings = "eqy", "eqy: splitnets, bind *, abc pdr"
        elif a.tool == "sby":
            variant, settings = f"noclk2ff:{engine}", NOCLK2FF
        else:
            variant, settings = "old" if bench in a.old_asserts else "new", a.prove
            if a.build:
                variant += "+" + "+".join(f.lstrip("-") for f in a.build)
        base = {"bench": bench, "axis": axis, "n": n, "variant": variant, "prove_args": settings}
        try:
            setup = setup_gen(n)
        except Exception as e:      # noqa: BLE001  a failed setup ends the search, as in the sby frontier
            self.record({**base, "run": f"<setup-failed n={n}>", "result": "SETUP_ERROR",
                         "reason": str(e).strip().split("\n")[0][:200]})
            return False
        run, limit = setup.export_dir.name, setup.params["timeout"]
        cached = self.done.get((bench, run, variant, settings))
        if cached:
            if (bench, axis, run, variant) not in self.on_axis:   # same design on another axis
                self.record({**cached, "axis": axis, "n": n})
            else:
                print(f"  {axis:24s} n={n:<6} {run:40s} {cached['result']:8s} (cached)", flush=True)
            return cached["result"] == "PASS"
        row = {**base, "run": run, "timeout": limit, "cells": setup.read_cells_from_stats_file()}
        case = {"bench": bench, "run": run, "asserts": variant.split("+")[0], "replace": [], "name": variant,
                "variant": variant, "dir": None, "sby": None, "task": None, "regen": [], "build": list(a.build),
                "gold": "gold.il", "gate": "gate.il"}
        if a.tool == "eqy":
            return self.step_eqy(row, case, limit)
        if a.tool == "sby":
            return self.step_sby(row, case, limit, engine)
        res = run_seq_prove(case, limit, a.prove, a.mem_cap, self.tagdir / bench / run / variant)
        self.record({**row, **res})
        return res["result"] == "PASS"

    def step_eqy(self, row, case, limit):
        """eqy on the run's gold and gate. All of eqy's time counts."""
        mdir = RUNS / "models" / case["bench"] / case["run"] / "eqy_inputs"
        if not (mdir / case["gate"]).exists():
            mdir.mkdir(parents=True, exist_ok=True)
            sby = run_bench.run_dir_of(case) / self.args.sby_file
            _script, files = build_model.read_sby(sby, None)
            build_model.copy_inputs(files, run_bench.run_dir_of(case), mdir, sby)
        res = run_eqy_step(case, limit, mdir, self.tagdir / case["bench"] / case["run"] / "eqy", self.args.eqy_jobs,
                           self.args.mem_cap, self.args.sby_file)
        self.record({**row, **res})
        return res["result"] == "PASS"

    def step_sby(self, row, case, limit, engine):
        """One sby engine on the plain miter without clk2fflogic, if the run passes the single-clock guard."""
        models = RUNS / "models" / case["bench"] / case["run"]
        mdir = models / "plain_inputs"
        if not (mdir / case["gate"]).exists():
            rdir = run_bench.run_dir_of(case)
            mdir.mkdir(parents=True, exist_ok=True)
            _script, files = build_model.read_sby(rdir / "miter.sby", None)
            build_model.copy_inputs(files, rdir, mdir, rdir / "miter.sby")
        res = run_noclk2ff(case, limit, engine, mdir, self.tagdir / case["bench"] / case["run"] / "noclk2ff",
                           models / "noclk2ff_guard", self.args.mem_cap)
        self.record({**row, **res})
        return res["result"] == "PASS"


def run_seq_prove(case, limit, prove, mem_cap, odir):
    """Build the model and run seq_prove within limit seconds, build included. Returns the row's result fields."""
    t0 = time.time()
    mdir, binfo, err = run_bench.build(case, rebuild=True, timeout=limit)
    bsecs = round(time.time() - t0, 1)
    if err:
        timed_out = err.startswith("build timeout")
        return {"result": "UNKNOWN" if timed_out else "ERROR", "reason": f"build: {err}", "build_secs": bsecs,
                "total_secs": bsecs}
    left = int(limit - bsecs)
    if left < 1:
        return {"result": "UNKNOWN", "reason": "the model build alone used the time limit", "build_secs": bsecs,
                "total_secs": bsecs}
    r = run_bench.prove(case, mdir, binfo, SimpleNamespace(prove=prove, timeout=left, mem_cap=mem_cap), odir)
    total = round(bsecs + r["wall_secs"], 1)
    result, reason = r["result"], r.get("reason", "")
    if result == "PASS" and total > limit:     # seq_prove only got the time left after the build
        result, reason = "UNKNOWN", f"PASS only after {total}s, over the limit"
    return {"result": result, "reason": reason, "build_secs": bsecs, "prove_secs": r["wall_secs"], "total_secs": total,
            **{k: r.get(k) for k in ("properties", "properties_proven", "candidates", "candidates_proven")}}


def run_eqy_step(case, limit, mdir, odir, eqy_jobs, mem_cap, sby_file):
    """eqy on mdir's gold and gate, with the liberty lines of sby_file. All of eqy's time counts."""
    ns = SimpleNamespace(eqy_timeout=limit, timeout=limit, eqy_pdr_timeout=None, eqy_jobs=eqy_jobs, mem_cap=mem_cap,
                         sby_file=sby_file)
    r = run_bench.run_eqy(case, mdir, ns, odir)
    result, reason, total = r["result"], r.get("reason", ""), r.get("wall_secs")
    if result == "PASS" and total > limit:
        result, reason = "UNKNOWN", f"PASS only after {total}s, over the limit"
    return {"result": result, "reason": reason, "prove_secs": total, "total_secs": total}


def noclk2ff_guard(rdir, gdir, replace=None):
    """seq_prove's single-clock checks on the plain design: build_model's guards on the script of miter.sby,
    then one clock net in the model. Returns the error or None, cached in gdir. replace maps input names to
    files that are swapped in (a mutant), which then needs a gdir of its own."""
    try:
        script, files = build_model.read_sby(rdir / "miter.sby", None)
        ys = "\n".join(build_model.yosys_script(script, "miter.v", "miter.v", allow_latches=False)) + "\n"
    except SystemExit as e:
        return str(e)
    done = gdir / "guard.txt"
    if done.exists() and (gdir / "build.ys").read_text() == ys:
        return None if done.read_text() == "OK" else done.read_text()
    gdir.mkdir(parents=True, exist_ok=True)
    build_model.copy_inputs(files, rdir, gdir, rdir / "miter.sby")
    for name, path in (replace or {}).items():
        shutil.copyfile(path, gdir / name)
    (gdir / "build.ys").write_text(ys)
    try:
        p = subprocess.run(run_bench.CAP + ["yosys", "-q", "-l", "build.log", "build.ys"], cwd=gdir,
                           capture_output=True, text=True, timeout=GUARD_TIMEOUT, check=False)
    except subprocess.TimeoutExpired:
        return f"yosys timeout after {GUARD_TIMEOUT}s"        # not cached
    log = (gdir / "build.log").read_text() if (gdir / "build.log").exists() else ""
    if p.returncode:
        guard = re.findall(r"GUARD: (.*)", log)
        err = (f"model has {guard[-1]}" if guard and "Assertion failed: selection" in log + p.stderr
               else f"yosys failed: {(p.stderr or log).strip()[-300:]}")
    else:
        nets = Model(gdir / "model.smt2").clock_nets()
        err = f"{len(nets)} clock nets {list(nets.values())[:3]}" if len(nets) > 1 else None
        (gdir / "model.smt2").unlink()
    done.write_text(err or "OK")
    return err


def run_noclk2ff(case, limit, engine, mdir, odir, gdir, mem_cap, replace=None):
    """One sby engine on the plain miter without clk2fflogic (written into the case's run dir), on mdir's
    inputs, if the design with replace swapped in passes the single-clock guard."""
    src = FRONTIER / case["bench"] / "run" / case["run"]
    t0 = time.time()
    err = noclk2ff_guard(src, gdir, replace)
    gsecs = round(time.time() - t0, 1)
    if not err:
        try:
            (run_bench.run_dir_of(case) / NOCLK2FF).write_text(noclk2ff_sby((src / "miter.sby").read_text()))
        except ValueError as e:
            err = str(e)
    if err:
        return {"result": "ERROR", "reason": f"guard: {err}", "build_secs": gsecs}
    ns = SimpleNamespace(sby=engine, sby_timeout=limit, sby_first=False, mem_cap=mem_cap, sby_file=NOCLK2FF)
    r = run_bench.run_sby({**case, "sby": NOCLK2FF}, mdir, ns, odir)[0]
    result, reason, total = r["result"], r["reason"], r["wall_secs"]
    if result == "PASS" and total > limit:
        result, reason = "UNKNOWN", f"PASS only after {total}s, over the limit"
    return {"result": result, "reason": reason, "build_secs": gsecs, "prove_secs": total, "total_secs": total}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("specs", nargs="+", metavar="SPEC")
    ap.add_argument("--tag", required=True)
    ap.add_argument("--tool", default="seq_prove", choices=["seq_prove", "eqy", "sby"])
    ap.add_argument("--engines", default="abc-pdr,aiger-suprove",
                    help=f"--tool sby: sby tasks, one search each (of {', '.join(PROVE_ENGINES)})")
    ap.add_argument("--prove", default="--k 2 --chunk 16 --model", help="seq_prove.py options")
    ap.add_argument("--eqy-jobs", type=int, default=8, help="eqy -j")
    ap.add_argument("--sby-file", default="miter_extra_asserts.sby", help="sby file with eqy's liberty lines")
    ap.add_argument("--old-asserts", default="", help="comma-separated benchmarks that use the run's asserts.vh")
    ap.add_argument("--build", action="append", default=[], help="extra build_model flag, e.g. --fsm-candidates")
    ap.add_argument("--orfs", action="store_true", help="also the ORFS axes")
    ap.add_argument("--mem-cap", help="run builds and seq_prove in a systemd slice with this MemoryMax")
    args = ap.parse_args()
    args.old_asserts = {b for b in args.old_asserts.split(",") if b}
    engines = args.engines.split(",") if args.tool == "sby" else [None]
    if args.tool == "sby" and not set(engines) <= set(PROVE_ENGINES):
        ap.error(f"--engines: only prove-mode engines ({', '.join(PROVE_ENGINES)})")
    run_bench.become_subreaper()
    if args.mem_cap:
        run_bench.setup_mem_cap(args.mem_cap)
    search = Search(args)
    summary = []
    for spec in args.specs:
        bench, _, want = spec.partition(":")
        axes = load_axes(bench)
        from _common.bench import find_frontier
        for name, setup_gen, _tasks, start, *rest in axes:
            if (want and want not in name) or ("ORFS" in name and not args.orfs):
                continue
            min_n = rest[0] if rest else 1
            step = rest[1] if len(rest) > 1 else None
            for engine in engines:
                tool = f"{args.tool}:{engine}" if engine else args.tool
                print(f"=== {bench}: {name} ({tool})", flush=True)
                n = find_frontier(lambda k, b=bench, g=setup_gen, a=name, e=engine: search.step(b, a, g, k, e),
                                  start=start, min_n=min_n, step=step)
                hit = setup_gen(n) if n >= min_n else None
                base = baseline(bench, name)
                summary.append({"tool": tool, "bench": bench, "axis": name, "frontier_n": n,
                                "run": hit.export_dir.name if hit else "-",
                                "cells": hit.read_cells_from_stats_file() if hit else 0,
                                **{f"{f}_{k}": v for f, b in base.items()
                                   for k, v in zip(("cells", "run", "engine"), b)}})
                print(f"{tool} frontier: n={n} ({summary[-1]['run']}, {summary[-1]['cells']} cells); prove-mode "
                      f"sby: MI {base['MI'][0]} cells ({base['MI'][2]}), IA {base['IA'][0]} cells "
                      f"({base['IA'][2]})", flush=True)
    out = search.tagdir / "frontier_summary.csv"
    with open(out, "a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0]))
        if fh.tell() == 0:
            w.writeheader()
        w.writerows(summary)
    print(f"summary: {out}")


if __name__ == "__main__":
    main()
