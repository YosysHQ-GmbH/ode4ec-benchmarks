#!/usr/bin/env python3
"""Build models and run seq_prove (and optionally sby) on a list of benchmark cases.

usage: run_bench.py CASES --tag TAG [--prove "--k 2 --chunk 16 --model"] [--timeout 300]
                    [--jobs 1] [--sby TASK,TASK [--sby-timeout 300]] [--eqy [--eqy-timeout S]]
                    [--only SUBSTRING] [--rebuild]

CASES: one case per line, `#` comments:
    BENCH RUN [asserts=old|new] [name=LABEL] [replace=NAME=PATH ...]
              [dir=PATH] [sby=FILE] [task=T] [regen=KEY=FILE ...] [build=FLAG ...] [gold=FILE] [gate=FILE]
  BENCH/RUN: internal_assertions_frontier_checks/<BENCH>/run/<RUN>, or dir= (relative to the repo).
  asserts=new regenerates the candidates; replace= swaps an input (mutants); name= labels the variant;
  sby= / task= the sby file and task for the build, --sby and eqy's liberty lines; regen= / build= extra
  build_model options; gold= / gate= eqy's inputs (default gold.il, gate.il).

Models are cached in seqprove/runs/models/, results go to seqprove/runs/<TAG>/ (results.csv: one row per
tool). A timeout is UNKNOWN; an sby PASS outside prove mode is UNKNOWN ("bounded"). Cases run one at a
time (--jobs N: N seq_prove cases in parallel); the sby tasks of a case run in parallel.
"""
import argparse
import csv
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOP = HERE.parent                   # seqprove/: the tool dir, runs/ and old records
REPO = TOP.parent
FRONTIER = REPO / "internal_assertions_frontier_checks"
RUNS = TOP / "runs"

FIELDS = ["tag", "bench", "run", "variant", "tool", "result", "reason", "asserts", "properties",
          "properties_proven", "candidates", "candidates_proven", "candidates_falsified", "candidates_retracted",
          "L0", "L1", "sweeps", "checks", "build_secs", "load_secs", "base_secs", "step_L0_secs",
          "step_L1_secs", "solve_secs", "wall_secs", "args"]


SLICE = "seqprove.slice"
SLICE_DIR = Path(f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/{SLICE}")
CAP = []            # command prefix that runs a process inside the capped slice (set by --mem-cap)


def setup_mem_cap(cap):
    """Run everything in one systemd user slice with MemoryMax=cap and no swap (OOM kills stay inside)."""
    subprocess.run(["systemctl", "--user", "set-property", "--runtime", SLICE, f"MemoryMax={cap}",
                    "MemorySwapMax=0"], check=True)
    CAP[:] = ["systemd-run", "--user", "--scope", "--quiet", f"--slice={SLICE}", "--"]


def oom_kills():
    """OOM kills inside the slice so far (0 without --mem-cap)."""
    try:
        for ln in (SLICE_DIR / "memory.events").read_text().split("\n"):
            if ln.startswith("oom_kill "):
                return int(ln.split()[1])
    except OSError:
        pass
    return 0


def parse_cases(path, only):
    cases = []
    for ln in Path(path).read_text().split("\n"):
        tok = ln.split("#")[0].split()
        if len(tok) < 2:
            continue
        c = {"bench": tok[0], "run": tok[1], "asserts": "old", "replace": [], "name": None, "dir": None,
             "sby": None, "task": None, "regen": [], "build": [], "gold": "gold.il", "gate": "gate.il"}
        for t in tok[2:]:
            k, v = t.split("=", 1)
            if k in ("replace", "regen", "build"):
                c[k].append(v)
            elif k in ("asserts", "name", "dir", "sby", "task", "gold", "gate"):
                c[k] = v
            else:
                sys.exit(f"{path}: unknown case option {t!r}")
        c["variant"] = c["name"] or c["asserts"]
        if only and only not in f"{c['bench']}/{c['run']}/{c['variant']}":
            continue
        cases.append(c)
    return cases


def run_dir_of(case):
    return REPO / case["dir"] if case["dir"] else FRONTIER / case["bench"] / "run" / case["run"]


def asserts_name(case):
    """The candidate file in the model dir: the regen= name of `asserts`, else asserts.vh."""
    return dict(r.split("=", 1) for r in case["regen"]).get("asserts", "asserts.vh")


def build(case, rebuild, timeout=None):
    """The case's model dir, built by build_model.py unless it is cached with the same options."""
    mdir = RUNS / "models" / case["bench"] / case["run"] / case["variant"]
    cmd = [sys.executable, str(HERE / "build_model.py"), str(run_dir_of(case)), str(mdir)]
    if case["sby"]:
        cmd += ["--sby", case["sby"]]
    if case["task"]:
        cmd += ["--task", case["task"]]
    if case["asserts"] == "new":
        cmd += ["--regen", "--match-gate-wires", "--const-candidates"]
        for r in case["regen"]:
            cmd += ["--regen-name", r]
    cmd += case["build"]
    for r in case["replace"]:
        cmd += ["--replace", r]
    stamp = mdir / "build.cmd"
    if not rebuild and (mdir / "model.smt2").exists() and stamp.exists() and stamp.read_text() == shlex.join(cmd):
        return mdir, json.loads((mdir / "build.json").read_text()), None
    stamp.unlink(missing_ok=True)       # an interrupted build must not look cached
    oom0 = oom_kills()
    p = subprocess.Popen(CAP + cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_tree(p.pid)
        p.communicate()
        return mdir, None, f"build timeout after {timeout}s"
    if p.returncode:
        oom = " (OOM kill in the capped slice)" if oom_kills() > oom0 else ""
        return mdir, None, (err or out).strip().split("\n")[-1] + oom
    stamp.write_text(shlex.join(cmd))
    return mdir, json.loads((mdir / "build.json").read_text()), None


def prove(case, mdir, binfo, args, odir):
    odir.mkdir(parents=True, exist_ok=True)
    pargs = shlex.split(args.prove)
    cmd = [sys.executable, "-u", str(HERE / "seq_prove.py"), str(mdir / "model.smt2"),
           "--candidates", asserts_name(case), "--src", str(mdir / asserts_name(case)),
           "--src", str(mdir / "miter_comb.v"), "--out", str(odir), "--timeout", str(args.timeout)] + pargs
    t0 = time.time()
    oom0 = oom_kills()
    with open(odir / "seq.log", "w") as log:
        p = subprocess.Popen(CAP + cmd, stdout=log, stderr=subprocess.STDOUT)
        try:
            p.wait(timeout=args.timeout + 120)
        except subprocess.TimeoutExpired:
            kill_tree(p.pid)
            p.wait()
    wall = time.time() - t0
    if oom_kills() > oom0:
        return {"tool": "seq_prove", "result": "ERROR", "reason": f"OOM: killed by the {args.mem_cap} memory cap",
                "wall_secs": round(wall, 1), "args": args.prove, "build_secs": binfo.get("build_secs")}
    row = {"tool": "seq_prove", "wall_secs": round(wall, 1), "args": args.prove, "build_secs": binfo.get("build_secs")}
    summ = odir / "summary.json"
    if not summ.exists() or summ.stat().st_mtime < t0:
        row.update(result="UNKNOWN" if wall >= args.timeout else "ERROR",
                   reason="hard timeout" if wall >= args.timeout else f"no summary, see {odir / 'seq.log'}")
        return row
    s = json.loads(summ.read_text())
    t = s.get("times", {})
    p, c = s.get("properties", {}), s.get("candidates", {})
    row.update(result=s["result"], reason=s["reason"], asserts=s.get("asserts"), properties=p.get("total"),
               properties_proven=p.get("proven"), candidates=c.get("total"), candidates_proven=c.get("proven"),
               candidates_falsified=c.get("falsified_base"), candidates_retracted=c.get("retracted"),
               L0=s.get("layer_counts", {}).get("0"), L1=s.get("layer_counts", {}).get("1"),
               sweeps=s.get("sweeps"), checks=s.get("checks"),
               load_secs=max(t.get("load_base", 0), t.get("load_step", 0)),
               base_secs=round(t.get("base_L0", 0) + t.get("base_L1", 0), 2),
               step_L0_secs=t.get("step_L0"), step_L1_secs=t.get("step_L1"), solve_secs=t.get("total"))
    return row


def _descendants(root):
    children = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            stat = Path(f"/proc/{d}/stat").read_text()
        except OSError:
            continue
        state, ppid = stat[stat.rindex(")") + 2:].split()[:2]
        if state == "Z":
            continue
        children.setdefault(int(ppid), []).append(int(d))
    out, stack = [], [root]
    while stack:
        pid = stack.pop()
        out.append(pid)
        stack.extend(children.get(pid, []))
    return out


def kill_tree(root):
    """SIGKILL root and all descendants (sby engines run in process groups of their own)."""
    own = os.getpgrp()
    for _ in range(10):
        pids = _descendants(root)
        alive = False
        for pid in pids:
            try:
                g = os.getpgid(pid)
                if g != own:
                    os.killpg(g, signal.SIGKILL)
                os.kill(pid, signal.SIGKILL)
                alive = True
            except ProcessLookupError:
                pass
        if not alive:
            return
        time.sleep(0.2)


def become_subreaper():
    """Adopt orphaned engines (PR_SET_CHILD_SUBREAPER) so reap_leftovers() finds them; Linux only."""
    try:
        import ctypes
        ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)
    except (OSError, AttributeError):
        pass


def reap_leftovers():
    """Kill and reap every process still below us (call only when no child should be running)."""
    for pid in _descendants(os.getpid())[1:]:
        kill_tree(pid)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if os.waitpid(-1, os.WNOHANG)[0] == 0:
                if len(_descendants(os.getpid())) == 1:
                    break
                time.sleep(0.1)       # killed processes not yet dead
        except ChildProcessError:
            break


def run_sby(case, mdir, args, odir):
    """The benchmark's own sby flow on this model dir's inputs (including a replaced gate)."""
    sby_file = case["sby"] or args.sby_file
    text = (run_dir_of(case) / sby_file).read_text()
    out, sec = [], None
    for ln in text.split("\n"):
        m = re.match(r"^\[(\w+)\]", ln)
        if m:
            sec = m.group(1)
        elif sec == "files" and ln.strip() and not ln.strip().startswith("#"):
            parts = ln.split()                    # `src` or `dest src`
            ln = str(mdir / (parts[0] if len(parts) == 2 else Path(parts[0]).name))
        elif sec == "options":
            ln = re.sub(r"\btimeout\s+\d+", f"timeout {args.sby_timeout}", ln)
        out.append(ln)
    odir.mkdir(parents=True, exist_ok=True)
    sby = odir / f"{Path(sby_file).stem}.sby"
    sby.write_text("\n".join(out))
    modes = dict(re.findall(r"^(\S+): mode (\w+)", text, re.MULTILINE))
    procs = {}
    for task in args.sby.split(","):
        d = odir / f"sby_{Path(sby_file).stem}_{task}"
        # own process group, so that the engines die with sby
        procs[task] = (subprocess.Popen(CAP + ["sby", "-f", "-d", str(d), str(sby), task], start_new_session=True,
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), d)
    t0 = time.time()
    oom0 = oom_kills()
    status, ended, stopped = {}, {}, set()

    def status_of(d):
        return next((f for f in ("PASS", "FAIL", "UNKNOWN", "TIMEOUT", "ERROR") if (d / f).exists()), None)

    def killgroup(p):
        kill_tree(p.pid)
        p.wait()

    while len(ended) < len(procs):
        for task, (p, d) in procs.items():
            if task not in ended and p.poll() is not None:
                ended[task], status[task] = time.time() - t0, status_of(d)
                killgroup(p)                      # leftover engines
        decided = any(status.get(t) in ("PASS", "FAIL") and modes.get(t) == "prove" for t in ended)
        overdue = time.time() - t0 > args.sby_timeout + 300
        if (args.sby_first and decided) or overdue:
            for task, (p, d) in procs.items():
                if task not in ended:
                    killgroup(p)
                    ended[task], status[task] = time.time() - t0, None
                    stopped.add(task)
        time.sleep(0.5)
    reap_leftovers()
    oom = oom_kills() > oom0
    rows = []
    for task, (p, d) in procs.items():
        mode, st = modes.get(task, "?"), status[task]
        result, reason = st or "ERROR", f"sby {st or 'no status'} (mode {mode})"
        if task in stopped:
            result, reason = "UNKNOWN", "stopped: another engine decided first" if args.sby_first else "hard timeout"
        elif st in (None, "ERROR") and oom:
            # an OOM kill in the slice and no verdict of its own
            result, reason = "ERROR", f"OOM: killed by the {args.mem_cap} memory cap (sby status {st})"
        elif st == "TIMEOUT":
            result, reason = "UNKNOWN", "timeout" + (" (another engine of this case was OOM-killed)" if oom else "")
        elif st == "PASS" and mode != "prove":
            result, reason = "UNKNOWN", f"{mode} passed (bounded, not a proof)"
        rows.append({"tool": f"sby:{Path(sby_file).stem}:{task}", "result": result, "reason": reason,
                     "wall_secs": round(ended[task], 1), "args": f"timeout {args.sby_timeout}"})
    return rows


# Gold and gate: flatten, delete unused blackboxes (a used one fails `hierarchy -check`) and remove the design's
# own asserts and covers as the sby flow does. Any other formal cell is an error because eqy would assume it.
EQY_PREP = ["hierarchy -auto-top", "flatten", "delete =A:blackbox", "hierarchy -check",
            "chformal -assert -remove", "chformal -cover -remove",
            "select -assert-none t:$assume t:$check t:$live t:$fair", "rename -top top"]


def eqy_config(case, mdir, args, pdr_timeout):
    """eqy config for the case's gold and gate, with the `read_liberty` lines of the sby script.
    `splitnets on` makes gate bit names match gold vectors, `bind *` asserts matched nets instead of assuming
    them, and the only strategy is sby abc pdr.

    No `sat` strategy: after the gate's `formalff -ff2anyinit`, `sat -tempinduct -set-init-undef
    -set-def-formal` has no model once a partition holds a gate flip-flop, so it passes any sequential
    difference (yosys 0.69+158, eqy 8770b67)."""
    libs, sec = [], None
    for ln in (run_dir_of(case) / (case["sby"] or args.sby_file)).read_text().split("\n"):
        m = re.match(r"^\[(\w+)\]", ln)
        if m:
            sec = m.group(1)
        elif sec == "script" and ln.split()[:1] == ["read_liberty"]:
            tok = ln.split()
            for i, t in enumerate(tok[1:], 1):
                if not t.startswith("-"):
                    tok[i] = str(mdir / t)
                    if not Path(tok[i]).exists():
                        raise FileNotFoundError(f"liberty file {tok[i]} not found")
            libs.append(" ".join(tok))
    return "\n".join(["[options]", "splitnets on", "",
                      "[gold]", f"read_rtlil {mdir / case['gold']}", *EQY_PREP, "",
                      "[gate]", *libs, f"read_rtlil {mdir / case['gate']}", *EQY_PREP, "",
                      "[collect *]", "bind *", "",
                      "[strategy pdr]", "use sby", "engine abc pdr", f"timeout {pdr_timeout}", ""])


def eqy_outputs_compared(wd):
    """(gold output bits, output bits some partition asserts under CHECK_OUTPUTS)."""
    gold = {ln.split()[1] for ln in (wd / "gold.ids").read_text().split("\n")
            if ln.startswith("top ") and "P=O" in ln.split()}
    checked = set()
    for sv in (wd / "partitions").glob("*.sv"):
        block = re.search(r"`ifdef CHECK_OUTPUTS\n(.*?)`endif", sv.read_text(), re.DOTALL)
        if block:
            checked.update(re.findall(r'"assert"\) \\__po_(\S+)__assert ', block.group(1)))
    return gold, checked


def run_eqy(case, mdir, args, odir):
    """eqy on the case. This is not the miter's property: there is no reset assumption, gate flip-flops start
    anywhere and gold `x` is a don't-care. ERROR also covers a gold output that was not compared."""
    limit = args.eqy_timeout or args.timeout
    pdr_timeout = args.eqy_pdr_timeout or limit
    odir.mkdir(parents=True, exist_ok=True)
    row = {"tool": "eqy", "args": f"splitnets, bind *, abc pdr timeout {pdr_timeout}, "
                                  f"-j {args.eqy_jobs}, limit {limit}s"}
    try:
        (odir / "case.eqy").write_text(eqy_config(case, mdir, args, pdr_timeout))
    except FileNotFoundError as e:
        return {**row, "result": "ERROR", "reason": str(e)}
    wd = odir / "eqy"
    t0 = time.time()
    oom0 = oom_kills()
    with open(odir / "eqy.log", "w") as log:
        p = subprocess.Popen(CAP + ["eqy", "-f", "-j", str(args.eqy_jobs), "-d", str(wd), str(odir / "case.eqy")],
                             cwd=odir, start_new_session=True, stdout=log, stderr=subprocess.STDOUT)
        timed_out = False
        try:
            p.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            timed_out = True
        kill_tree(p.pid)
        p.wait()
    reap_leftovers()
    row["wall_secs"] = round(time.time() - t0, 1)
    if oom_kills() > oom0:
        return {**row, "result": "ERROR", "reason": f"OOM: killed by the {args.mem_cap} memory cap"}
    targets = wd / "summary_targets.list"
    if not targets.exists():
        if timed_out:
            return {**row, "result": "UNKNOWN", "reason": "timeout before partitioning finished"}
        last = [ln for ln in (odir / "eqy.log").read_text().split("\n") if "ERROR" in ln][-1:]
        return {**row, "result": "ERROR", "reason": last[0].strip() if last else f"see {odir / 'eqy.log'}"}

    status = {}                                  # partition -> status, None if unfinished
    for t in targets.read_text().split():
        part = t.split("/")[1]
        f = wd / t
        status[part] = f.read_text().split()[0] if f.exists() and f.read_text().strip() else None
    n = len(status)
    proven = sum(s == "PASS" for s in status.values())
    gold, checked = eqy_outputs_compared(wd)
    missing = sorted(o for o in gold if o not in checked and re.sub(r"\[\d+\]$", "", o) not in checked)
    summary = f"{proven}/{n} partitions proven, {len(gold)} output bits"
    if not gold or not n:
        return {**row, "result": "ERROR", "reason": f"nothing compared: {summary}"}
    if missing:
        return {**row, "result": "ERROR", "reason": f"{len(missing)} gold output bits not compared "
                                                    f"(e.g. {', '.join(missing[:3])}); {summary}"}
    failed = sorted(k for k, s in status.items() if s == "FAIL")
    if failed:
        return {**row, "result": "FAIL", "reason": f"partition counterexample in {', '.join(failed[:3])}"
                                                   f"{' ...' if len(failed) > 3 else ''}; {summary}"}
    if timed_out or None in status.values():
        return {**row, "result": "UNKNOWN", "reason": f"timeout; {summary}"}
    if "ERROR" in status.values():
        return {**row, "result": "ERROR", "reason": f"strategy error; {summary}, see {wd}"}
    if proven < n:
        return {**row, "result": "UNKNOWN", "reason": summary}
    return {**row, "result": "PASS", "reason": summary}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cases")
    ap.add_argument("--tag", required=True, help="results go to seqprove/runs/<TAG>/")
    ap.add_argument("--prove", default="--k 2 --chunk 16 --model", help="seq_prove.py options")
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--jobs", type=int, default=1)
    ap.add_argument("--sby", default="", help="comma-separated sby tasks to run as well (one case at a time)")
    ap.add_argument("--sby-timeout", type=int, default=300)
    ap.add_argument("--sby-file", default="miter_extra_asserts.sby",
                    help="sby file of the run dir (miter.sby: the plain miter without internal asserts)")
    ap.add_argument("--sby-first", action="store_true",
                    help="stop the other sby tasks of a case once one decided (PASS/FAIL in prove mode)")
    ap.add_argument("--eqy", action="store_true", help="run eqy as well (one case at a time, see run_eqy)")
    ap.add_argument("--eqy-timeout", type=int, help="wall limit of one eqy run (default: --timeout)")
    ap.add_argument("--eqy-pdr-timeout", type=int, help="sby timeout of the pdr strategy per partition "
                                                        "(default: the eqy wall limit)")
    ap.add_argument("--eqy-jobs", type=int, default=8, help="eqy -j: partitions run in parallel")
    ap.add_argument("--no-prove", action="store_true", help="only build (and sby, eqy)")
    ap.add_argument("--only", help="only cases whose BENCH/RUN/variant contains this")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--mem-cap", help="e.g. 16G: run builds, seq_prove and sby in one systemd user slice with "
                                      "this MemoryMax and no swap; OOM kills are reported as ERROR")
    args = ap.parse_args()
    become_subreaper()
    if args.mem_cap:
        setup_mem_cap(args.mem_cap)

    cases = parse_cases(args.cases, args.only)
    tagdir = RUNS / args.tag
    tagdir.mkdir(parents=True, exist_ok=True)
    csv_path = tagdir / "results.csv"
    new_file = not csv_path.exists()
    with open(csv_path, "a", newline="") as fh:
        run_cases(args, cases, tagdir, fh, new_file)


def run_cases(args, cases, tagdir, fh, new_file):
    """Build and prove every case, one row per result."""
    w = csv.DictWriter(fh, fieldnames=FIELDS)
    if new_file:
        w.writeheader()

    def emit(case, row):
        row = dict(tag=args.tag, bench=case["bench"], run=case["run"], variant=case["variant"], **row)
        w.writerow(row)
        fh.flush()
        print(f"{case['bench']:14s} {case['run']:22s} {case['variant']:8s} {row['tool']:20s} "
              f"{row['result']:8s} {row.get('wall_secs', '')!s:>7}s  {row.get('reason', '')}", flush=True)

    # builds one at a time (yosys memory), then the proofs
    built = []
    for case in cases:
        mdir, binfo, err = build(case, args.rebuild)
        if err:
            emit(case, {"tool": "build", "result": "ERROR", "reason": err})
            continue
        built.append((case, mdir, binfo))

    def one(item):
        case, mdir, binfo = item
        odir = tagdir / case["bench"] / case["run"] / case["variant"]
        return case, prove(case, mdir, binfo, args, odir)

    if not args.no_prove:
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
            for case, row in ex.map(one, built):
                emit(case, row)
    if args.sby:
        for case, mdir, _ in built:
            for row in run_sby(case, mdir, args, tagdir / case["bench"] / case["run"] / case["variant"]):
                emit(case, row)
    if args.eqy:
        for case, mdir, _ in built:
            emit(case, run_eqy(case, mdir, args, tagdir / case["bench"] / case["run"] / case["variant"]))


if __name__ == "__main__":
    main()
