# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "matplotlib>=3.11.1",
#     "polars>=1.43.2",
# ]
# ///
"""Mutation test at each tool's largest frontier PASS: are the PASSes the comparison counts sound?

usage: uv run frontier_mutants.py --tag TAG [--frontier TAG|CSV ...] [--pool 6] [--bmc-timeout 300] [--bmc-jobs 6]
                                  [--only SUBSTRING] [--list] [--mem-cap 16G]

Points: for each --frontier tag, tool and axis, the run of the largest PASS, with every setting that passed
there. The run's sby files are first rewritten by its axis' Setup, as a frontier step does.

Mutants: mutate.py on the run's gate.il (inverted, constant or cross-wired cell pins, seed 1, --pool per run),
shared by all points on that run. There are no off-by-one-cycle mutants.

A mutant counts as different only if BMC finds a counterexample within --bmc-timeout:
1. sby abc bmc3 on the run's own miter.sby. It keeps clk2fflogic, the reference semantics, so it does not
   depend on the one-step-per-cycle model that seq_prove, eqy and the noclk2ff variant use.
2. If 1 times out: the same BMC without clk2fflogic, which reaches twice as many cycles, and only on a mutant
   that passes the single-clock guard. For such a design both models agree. Check 2 relies on the same guard as
   the noclk2ff tool variant, so a hole in the guard can make a mutant look different but cannot hide a PASS.
   The variant column says which check confirmed a mutant.
The BMC checks run --bmc-jobs at a time, each in its own process, because run_sby kills every process below
its caller. The tools then run one at a time, as in the frontier, and only on the confirmed mutants.

Each tool runs as in its frontier step. FAIL is expected, UNKNOWN is a miss and PASS is a soundness bug,
with one exception to check by hand: eqy treats gold `x` as a don't-care where the miter reads 0, so an eqy
PASS can mean the mutant differs only where gold is x.

Writes seqprove/runs/TAG/mutants.csv, one row per check (a rerun skips rows already there), and a summary.
"""
import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from types import SimpleNamespace

import build_model
import frontier
import run_bench
from run_bench import FRONTIER, HERE, RUNS

DEFAULT_FRONTIERS = ["frontier_focused", "frontier_focused_eqy", "frontier_focused_noclk2ff"]
BMC = "miter_bmc.sby"
BMC_NOCLK2FF = "miter_bmc_noclk2ff.sby"
NOCLK2FF_BMC = "noclk2ff:abc-bmc3"
BMC_HEAD = """# written by seqprove/seqprove/frontier_mutants.py, a ground truth of the mutation test (a counterexample =
# the mutant differs from gold): the [script] and [files] of {src} under one BMC task
[tasks]
abc-bmc3

[options]
abc-bmc3: mode bmc
abc-bmc3: depth {depth}
abc-bmc3: timeout {timeout}

[engines]
abc-bmc3: abc bmc3

"""
FIELDS = ["bench", "axis", "run", "cells", "timeout", "tool", "variant", "mutant", "mutation", "result", "reason",
          "build_secs", "prove_secs", "total_secs"]


def tool_of(variant):
    return "eqy" if variant == "eqy" else "sby" if variant.startswith("noclk2ff:") else "seq_prove"


def select_points(tags):
    """Frontier rows of the largest PASS per tag, tool and axis, with every variant that passed that run."""
    best = {}
    for tag in tags:
        with open(tag if tag.endswith(".csv") else RUNS / tag / "frontier.csv") as fh:
            for r in csv.DictReader(fh):
                if r["result"] != "PASS":
                    continue
                key = (tag, tool_of(r["variant"]), r["bench"], r["axis"])
                top = best.get(key)
                if not top or int(r["cells"]) > int(top[0]["cells"]):
                    best[key] = [r]
                elif r["run"] == top[0]["run"] and r["variant"] not in {t["variant"] for t in top}:
                    top.append(r)
    points = {}
    for rows in best.values():                  # one point per variant and run
        for r in rows:
            p = points.setdefault((r["variant"], r["bench"], r["run"]), {**r, "axes": []})
            p["axes"].append(r["axis"])
    return list(points.values())


def refresh_sby_files(points):
    """Rewrite each point's sby files with its axis' Setup, as a frontier step does."""
    cwd = os.getcwd()
    for bench in sorted({p["bench"] for p in points}):
        gens = {a[0]: a[1] for a in frontier.load_axes(bench)}
        for p in (p for p in points if p["bench"] == bench):
            setup = gens[p["axis"]](int(p["n"]))
            if setup.export_dir.name != p["run"]:
                sys.exit(f"{bench} {p['axis']} n={p['n']}: Setup gives {setup.export_dir.name}, frontier {p['run']}")
    os.chdir(cwd)


def gate_top(il):
    """The gate netlist's top module: the one marked `top`, else the only one."""
    text = il.read_text()
    m = re.search(r"^attribute \\top 1\nmodule \\(\S+)", text, re.MULTILINE)
    mods = re.findall(r"^module \\(\S+)", text, re.MULTILINE)
    if m:
        return m.group(1)
    if len(mods) == 1:
        return mods[0]
    sys.exit(f"{il}: no module marked top among {mods[:5]}")


def make_mutants(rdir, root, pool):
    """{mNN: mutate command} for the run's gate, cached in root/mutants. Copies the run's inputs to root/orig."""
    orig = root / "orig"
    if not (orig / "gate.il").exists():
        orig.mkdir(parents=True, exist_ok=True)
        for sby in ("miter.sby", "miter_extra_asserts.sby"):
            if (rdir / sby).exists():
                _script, files = build_model.read_sby(rdir / sby, None)
                build_model.copy_inputs(files, rdir, orig, rdir / sby)
    mdir = root / "mutants"
    if not (mdir / "mutations.ys").exists():
        script, _files = build_model.read_sby(rdir / "miter.sby", None)
        libs = [orig / t for ln in script if ln.split()[:1] == ["read_liberty"] for t in ln.split()[1:]
                if not t.startswith("-")]
        cmd = [sys.executable, str(HERE / "mutate.py"), str(orig / "gate.il"), str(mdir), "--module",
               gate_top(orig / "gate.il"), "--n", str(pool), "--seed", "1"]
        if libs:                    # pin directions of the library cells
            cmd += ["--liberty", str(libs[0])]
        p = subprocess.run(run_bench.CAP + cmd, capture_output=True, text=True, check=False)
        print(f"  mutate.py: {(p.stdout + p.stderr).strip()}", flush=True)
        if p.returncode:
            sys.exit(f"mutate.py failed for {rdir}")
    return {m.group(1): m.group(2) for m in re.finditer(r"^(m\d+): (.*)$", (mdir / "mutations.ys").read_text(),
                                                        re.MULTILINE)}


def write_bmc_files(rdir, root, args):
    """Write root/BMC and root/BMC_NOCLK2FF. Returns False if miter.sby has no clk2fflogic to remove."""
    head = BMC_HEAD.replace("{depth}", str(args.bmc_depth)).replace("{timeout}", str(args.bmc_timeout))
    script, files = build_model.read_sby(rdir / "miter.sby", None)
    (root / BMC).write_text(head.replace("{src}", "miter.sby") + "\n".join(["[script]", *script, "", "[files]",
                                                                           *files, ""]))
    try:
        text = frontier.noclk2ff_sby((rdir / "miter.sby").read_text())
    except ValueError:
        return False
    (root / frontier.NOCLK2FF).write_text(text)
    script, files = build_model.read_sby(root / frontier.NOCLK2FF, None)
    (root / BMC_NOCLK2FF).write_text(head.replace("{src}", f"{frontier.NOCLK2FF} (miter.sby without clk2fflogic)")
                                     + "\n".join(["[script]", *script, "", "[files]", *files, ""]))
    return True


def sby_bmc(job, sby, odir):
    """sby abc bmc3 with root/sby on the mutant's inputs. Returns the row's result fields."""
    case = {"bench": job["bench"], "run": job["run"], "dir": job["root"], "sby": sby}
    ns = SimpleNamespace(sby="abc-bmc3", sby_timeout=job["timeout"], sby_first=False, mem_cap=job["mem_cap"])
    r = run_bench.run_sby(case, Path(job["root"]) / job["m"] / "inputs", ns, odir)[0]
    return {"result": r["result"], "reason": r["reason"], "prove_secs": r["wall_secs"], "total_secs": r["wall_secs"]}


def bmc_job(job):
    """The BMC checks of one mutant that are still missing, in a process of its own. Prints the new rows as
    JSON."""
    run_bench.become_subreaper()
    if job["mem_cap"]:
        run_bench.setup_mem_cap(job["mem_cap"])
    root, m, rows = Path(job["root"]), job["m"], []
    result = job["first"]
    if result is None:
        r = sby_bmc(job, BMC, root / m / "bmc")
        rows.append({"variant": "abc-bmc3", **r})
        result = r["result"]
    if result == "UNKNOWN" and job["fallback"]:
        rdir = FRONTIER / job["bench"] / "run" / job["run"]
        err = frontier.noclk2ff_guard(rdir, root / m / "bmc_noclk2ff_guard", {"gate.il": root / "mutants" / f"{m}.il"})
        if err:
            rows.append({"variant": NOCLK2FF_BMC, "result": "ERROR", "reason": f"guard: {err}"})
        else:
            rows.append({"variant": NOCLK2FF_BMC, **sby_bmc(job, BMC_NOCLK2FF, root / m / "bmc_noclk2ff")})
    print(json.dumps(rows))


def mutant_inputs(root, m):
    """root/<m>/inputs: the run's inputs with the mutant's gate.il."""
    d = root / m / "inputs"
    if not (d / "gate.il").exists():
        shutil.copytree(root / "orig", d, symlinks=True, dirs_exist_ok=True)
        shutil.copyfile(root / "mutants" / f"{m}.il", d / "gate.il")
    return d


def short(mutation):
    mode = re.search(r"-mode (\S+)", mutation)
    src = re.search(r"-src (\S+)", mutation)
    return f"{mode.group(1) if mode else '?'} {src.group(1) if src else ''}".strip()


class Runner:
    def __init__(self, args):
        self.args = args
        self.tagdir = RUNS / args.tag
        self.tagdir.mkdir(parents=True, exist_ok=True)
        self.csv = self.tagdir / "mutants.csv"
        self.done = {}
        if self.csv.exists():
            with open(self.csv) as fh:
                for r in csv.DictReader(fh):
                    self.done[(r["bench"], r["run"], r["variant"], r["mutant"])] = r

    def record(self, row):
        new = not self.csv.exists()
        with open(self.csv, "a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow(row)
        self.done[(row["bench"], row["run"], row["variant"], row["mutant"])] = row
        print(f"    {row['mutant']:4s} {row['tool']:9s} {row['variant']:24s} {row['result']:8s} "
              f"{row.get('total_secs') or '-'!s:>7}s / {row['timeout']}s  {row['reason']}", flush=True)

    def ground_truth(self, bases, root, fallback):
        """Run the missing BMC checks of the run's mutants. Returns the mutants with a counterexample."""
        jobs = []
        for m, base in bases.items():
            first = self.done.get((base["bench"], base["run"], "abc-bmc3", m))
            more = fallback and (base["bench"], base["run"], NOCLK2FF_BMC, m) not in self.done
            if first is None or (first["result"] == "UNKNOWN" and more):
                jobs.append({"bench": base["bench"], "run": base["run"], "root": str(root), "m": m,
                             "first": first and first["result"], "fallback": more, "timeout": self.args.bmc_timeout,
                             "mem_cap": self.args.mem_cap})
        with ThreadPoolExecutor(max_workers=self.args.bmc_jobs) as ex:
            futs = {ex.submit(self.run_job, job): job for job in jobs}
            for f in as_completed(futs):
                for row in f.result():
                    self.record({**bases[futs[f]["m"]], "tool": "bmc", "timeout": self.args.bmc_timeout, **row})
        return {m for m, b in bases.items() if any(self.done.get((b["bench"], b["run"], v, m), {}).get("result")
                                                  == "FAIL" for v in ("abc-bmc3", NOCLK2FF_BMC))}

    @staticmethod
    def run_job(job):
        p = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--bmc-job", json.dumps(job)],
                           capture_output=True, text=True, check=False)
        try:
            return json.loads(p.stdout.strip().split("\n")[-1])
        except (json.JSONDecodeError, IndexError):
            return [{"variant": "abc-bmc3" if job["first"] is None else NOCLK2FF_BMC, "result": "ERROR",
                     "reason": f"bmc_job failed (rc {p.returncode}): {(p.stderr or p.stdout).strip()[-300:]}"}]

    def tool(self, p, base, root, m, minputs):
        """The point's tool on the mutant, as in its frontier step."""
        variant = p["variant"]
        key = (p["bench"], p["run"], variant, m)
        if key in self.done:
            return self.done[key]
        a, limit, tool = self.args, int(p["timeout"]), tool_of(variant)
        odir = root / m / re.sub(r"[^\w.+-]", "_", variant)
        case = {"bench": p["bench"], "run": p["run"], "asserts": "old", "replace": [], "name": None,
                "variant": variant, "dir": None, "sby": None, "task": None, "regen": [], "build": [],
                "gold": "gold.il", "gate": "gate.il"}
        if tool == "seq_prove":
            asserts, *flags = variant.split("+")
            name = f"{variant}_mut_{m}"           # model dir name
            case.update(asserts=asserts, name=name, variant=name, build=[f"--{f}" for f in flags],
                        replace=[f"gate.il={root / 'mutants' / f'{m}.il'}"])
            res = frontier.run_seq_prove(case, limit, p["prove_args"], a.mem_cap, odir)
        elif tool == "eqy":
            res = frontier.run_eqy_step(case, limit, minputs, odir, a.eqy_jobs, a.mem_cap, a.sby_file)
        else:
            sdir = odir / "sby_file"
            sdir.mkdir(parents=True, exist_ok=True)
            res = frontier.run_noclk2ff({**case, "dir": str(sdir)}, limit, variant.split(":", 1)[1],
                                        minputs, odir, odir / "guard", a.mem_cap,
                                        {"gate.il": root / "mutants" / f"{m}.il"})
        self.record({**base, "tool": tool, "variant": variant, "timeout": limit, **res})
        return self.done[key]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--frontier", nargs="+", default=DEFAULT_FRONTIERS,
                    help="frontier tags (or frontier.csv paths) to take the points from")
    ap.add_argument("--pool", type=int, default=6, help="mutants per run")
    ap.add_argument("--bmc-timeout", type=int, default=300)
    ap.add_argument("--bmc-depth", type=int, default=2000, help="bmc3 frames (the timeout usually ends it first)")
    ap.add_argument("--bmc-jobs", type=int, default=6, help="mutants whose BMC runs at the same time")
    ap.add_argument("--eqy-jobs", type=int, default=8, help="eqy -j, as in the eqy frontier")
    ap.add_argument("--sby-file", default="miter_extra_asserts.sby", help="sby file with eqy's liberty lines")
    ap.add_argument("--only", help="only points whose BENCH/RUN/variant contains this")
    ap.add_argument("--list", action="store_true", help="print the points and stop")
    ap.add_argument("--mem-cap", help="run everything in a systemd slice with this MemoryMax")
    args = ap.parse_args()
    points = [p for p in select_points(args.frontier)
              if not args.only or args.only in f"{p['bench']}/{p['run']}/{p['variant']}"]
    points.sort(key=lambda p: (int(p["timeout"]), int(p["cells"])))
    for p in points:
        print(f"{p['bench']:12s} {p['run']:46s} {p['cells']:>7} cells  {p['timeout']:>4}s  {p['variant']:24s} "
              f"({', '.join(p['axes'])}; frontier {p['total_secs']}s)")
    if args.list:
        return
    run_bench.become_subreaper()
    if args.mem_cap:
        run_bench.setup_mem_cap(args.mem_cap)
    refresh_sby_files(points)
    runner = Runner(args)
    summary = []
    for bench, run in dict.fromkeys((p["bench"], p["run"]) for p in points):
        pts = [p for p in points if (p["bench"], p["run"]) == (bench, run)]
        print(f"=== {bench} {run}: {', '.join(p['variant'] for p in pts)}", flush=True)
        root = runner.tagdir / bench / run
        rdir = FRONTIER / bench / "run" / run
        muts = make_mutants(rdir, root, args.pool)
        base0 = {"bench": bench, "axis": "; ".join(pts[0]["axes"]), "run": run, "cells": pts[0]["cells"]}
        bases = {m: {**base0, "mutant": m, "mutation": short(mutation)} for m, mutation in muts.items()}
        for m in muts:
            mutant_inputs(root, m)
        confirmed = runner.ground_truth(bases, root, write_bmc_files(rdir, root, args))
        different = [(m, bases[m], root / m / "inputs") for m in muts if m in confirmed]
        by_noclk2ff = sum(runner.done[(bench, run, "abc-bmc3", m)]["result"] != "FAIL" for m, _b, _i in different)
        for p in pts:
            res = [runner.tool(p, {**base, "axis": "; ".join(p["axes"])}, root, m, minputs)["result"]
                   for m, base, minputs in different]
            summary.append({"bench": bench, "run": run, "variant": p["variant"], "mutants": len(muts),
                            "different": len(different), "by_noclk2ff_bmc": by_noclk2ff,
                            **{k: res.count(k) for k in ("FAIL", "UNKNOWN", "PASS")},
                            "ERROR": sum(r not in ("FAIL", "UNKNOWN", "PASS") for r in res)})
    if not summary:
        sys.exit("no points")
    print("\nsummary (tools run on the BMC-confirmed different mutants only):")
    for s in summary:
        flag = "  <-- PASS on a different mutant" if s["PASS"] else ""
        print(f"  {s['bench']:12s} {s['run']:46s} {s['variant']:24s} {s['different']}/{s['mutants']} different "
              f"({s['by_noclk2ff_bmc']} by the noclk2ff BMC): "
              f"FAIL {s['FAIL']} UNKNOWN {s['UNKNOWN']} PASS {s['PASS']} ERROR {s['ERROR']}{flag}")
    with open(runner.tagdir / "mutants_summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--bmc-job"]:
        bmc_job(json.loads(sys.argv[2]))
    else:
        main()
