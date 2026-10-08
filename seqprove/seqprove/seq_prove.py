#!/usr/bin/env python3
"""Prove the asserts of a flattened single-clock miter model with yosys-smtbmc --incremental
(Houdini k-induction with layered step checks, see houdini.py).

usage: seq_prove.py model.smt2 --candidates asserts.vh [--src asserts.vh --src miter_comb.v]
                    [--k K] [--solver S] [--chunk N] [--model] [--layers auto|off]
                    [--out DIR] [--timeout SECONDS]

Asserts from a --candidates file are candidates, all others properties. Exit code: 0 PASS (all properties
proven), 1 FAIL (falsified from the initial state), 2 UNKNOWN (not inductive, or timeout), 3 ERROR
(unsupported or vacuous model, tool failure). --out DIR writes summary.json and checks.jsonl.
Relies on build_model.py's guards (no negedge or derived clocks, no latches). Checks itself that the model is
flat and has one clock.
"""
import argparse
import json
import os
import re
import signal
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from houdini import BASE_FAIL, STEP_FAIL, Prover, Timeout
from model import Model, ModelError

EXIT = {"PASS": 0, "FAIL": 1, "UNKNOWN": 2, "ERROR": 3}


def labels_from_src(model, src_files):
    """Readable label per assert: the text of its source line, if that file was given with --src."""
    text = {}
    for f in src_files:
        try:
            with open(f) as fh:
                text[os.path.basename(f)] = fh.read().split("\n")
        except OSError as e:
            print(f"WARNING: --src {f}: {e}", file=sys.stderr)
    labels = {}
    for i in model.assert_loc:
        lines, ln = text.get(model.src_file(i)), model.src_line(i)
        if lines and ln and ln <= len(lines):
            labels[i] = re.sub(r"^assert\((.*)\);$", r"\1", lines[ln - 1].strip())
    return labels


def log_of_run(run_dir, model, k, layers, option):
    """The records of an earlier run's checks.jsonl (its --out dir), for --drop-from / --resume-from.
    Refuses a run of another model, k or layer setting."""
    try:
        with open(os.path.join(run_dir, "summary.json")) as fh:
            summ = json.load(fh)
    except (OSError, ValueError) as e:
        raise ModelError(f"{option} {run_dir}: no readable summary.json ({e})") from None
    log = os.path.join(run_dir, "checks.jsonl")
    same = (os.path.realpath(summ.get("smt2", "")) == os.path.realpath(model.path)
            and summ.get("asserts") == len(model.assert_loc) and summ.get("k") == k
            and summ.get("layers") == layers and os.path.getmtime(model.path) <= os.path.getmtime(log))
    if not same:
        raise ModelError(f"{option} {run_dir}: not a run of this model with the same --k and --layers "
                         "(or the model was rebuilt since)")
    records = []
    with open(log) as fh:
        for ln in fh:
            try:
                records.append(json.loads(ln))
            except ValueError:              # last line of a killed run
                continue
    return records


def drops_of_run(records):
    """--drop-from: the asserts that run dropped by a counterexample before its first query timeout."""
    ids = []
    for r in records:
        if r.get("event") in ("restart", "solver_timeout"):
            break
        if r.get("event") == "drop":
            if r["reason"] not in (BASE_FAIL, STEP_FAIL):
                break
            ids.append(r["id"])
        elif r.get("event") == "pre_drop":
            ids += r["ids"]
    return ids


def state_of_run(records):
    """--resume-from: (every assert that run retracted, the ones its unfinished last sweep had proven)."""
    dropped, checked = [], set()
    for r in records:
        event = r.get("event")
        if event == "drop":
            dropped.append(r["id"])
        elif event == "pre_drop":
            dropped += r["ids"]
        elif event == "sanity" and r["which"].startswith("step_sweep_"):    # a sweep ended
            checked.clear()
        elif event is None and r.get("session") in ("step", "wide") and r.get("result") == "unsat":
            checked.update(r["ids"])
    return dropped, checked - set(dropped)


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("smt2")
    ap.add_argument("--candidates", action="append", default=[],
                    help="file (basename) whose asserts are generated candidates; repeatable")
    ap.add_argument("--src", action="append", default=[], help="source file for readable assert labels")
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--solver", default="yices")
    ap.add_argument("--declare", action="store_true",
                    help="bind hypotheses with declare-const + assert(=) (needed for boolector; implied by it)")
    ap.add_argument("--order", default="index", choices=["index", "reverse", "random", "values-first"],
                    help="check order within a layer; values-first: constraints on register values before "
                         "equalities between registers (same result, usually fewer sweeps)")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--chunk", type=int, default=1,
                    help="check N asserts per query (disjunction of negations); on sat fall back to one by one")
    ap.add_argument("--goal", default="push", choices=["push", "assume"])
    ap.add_argument("--model", action="store_true",
                    help="on sat, drop EVERY live assert the model violates (not only the checked ones)")
    ap.add_argument("--layers", default="auto", choices=["auto", "off"],
                    help="auto: check non-register asserts with register asserts assumed at step K; "
                         "off: every assert is layer 0")
    ap.add_argument("--wide-bits", type=int, default=64,
                    help="asserts comparing at least this many bits are checked one at a time with --wide-solver "
                         "(yices is slow on wide queries); 0 = off")
    ap.add_argument("--wide-solver", default="boolector")
    ap.add_argument("--query-timeout", type=float, default=0,
                    help="seconds per solver check. A check over it rebuilds the session and splits the chunk; "
                         "a single assert that still times out is retracted (a property then ends UNKNOWN). "
                         "0 = off")
    ap.add_argument("--timeout-siblings", action="store_true",
                    help="with --query-timeout: when a bit of a register times out, retract the other bits of "
                         "the register (same label up to bit indices) without checking them")
    ap.add_argument("--sibling-max", type=int, default=128,
                    help="--timeout-siblings: a name with more bits than this (a wide struct) only loses its "
                         "bits in the chunk that timed out")
    ap.add_argument("--session-mem-gb", type=float, default=0,
                    help="rebuild a solver session that uses more memory than this; 0 = off, needs /proc")
    ap.add_argument("--defer-implied", action="store_true",
                    help="leave guarded equalities `G || (A[hi:lo] == B[hi:lo])` unchecked and unused while all "
                         "bit equalities `A[i] == B[i]` that imply them are live (needs --src)")
    ap.add_argument("--drop-from", metavar="RUN_DIR",
                    help="start without the candidates an earlier run (its --out dir; same model, --k and "
                         "--layers) dropped by a counterexample before its first query timeout")
    ap.add_argument("--resume-from", metavar="RUN_DIR",
                    help="continue an unfinished run (same model, --k and --layers): start without everything "
                         "it retracted, and check first what its last sweep did not reach")
    ap.add_argument("--out", help="directory for summary.json and checks.jsonl")
    ap.add_argument("--timeout", type=int, default=0, help="wall-clock limit in seconds (result UNKNOWN)")
    args = ap.parse_args()
    if args.solver == "boolector":
        args.declare = True
    if not args.candidates:
        print("WARNING: no --candidates file: every assert is treated as a property", file=sys.stderr)
    if args.drop_from and args.resume_from:
        ap.error("--drop-from and --resume-from: give one of them")
    earlier = args.drop_from or args.resume_from
    if args.out and earlier and os.path.realpath(args.out) == os.path.realpath(earlier):
        ap.error("--out is the directory of the earlier run (--drop-from / --resume-from)")
    return args


def prove(args, log):
    """The result as a dict (summary.json). Never raises."""
    try:
        model = Model(args.smt2, args.candidates)
        pre, checked = (), ()
        if args.drop_from:
            pre = drops_of_run(log_of_run(args.drop_from, model, args.k, args.layers, "--drop-from"))
        elif args.resume_from:
            pre, checked = state_of_run(log_of_run(args.resume_from, model, args.k, args.layers, "--resume-from"))
        prover = Prover(model, k=args.k, solver=args.solver, declare=args.declare, chunk=args.chunk,
                        goal=args.goal, use_model=args.model, layers=args.layers, order=args.order,
                        seed=args.seed, labels=labels_from_src(model, args.src),
                        log=log, echo=lambda s: print(s, flush=True),
                        wide_bits=args.wide_bits, wide_solver=args.wide_solver, query_timeout=args.query_timeout,
                        timeout_siblings=args.timeout_siblings, sibling_max=args.sibling_max,
                        session_mem_mb=args.session_mem_gb * 1024, defer_implied=args.defer_implied,
                        pre_drop=pre, check_last=checked)
        return prover.run()
    except ModelError as e:
        return {"result": "ERROR", "reason": str(e), "smt2": args.smt2}
    except Timeout:
        return {"result": "UNKNOWN", "reason": "timeout before the proof started", "smt2": args.smt2}
    except Exception as e:  # noqa: BLE001  a bug must never look like PASS/FAIL (exit code 1 is FAIL)
        traceback.print_exc()
        return {"result": "ERROR", "reason": f"internal error: {type(e).__name__}: {e}", "smt2": args.smt2}


def print_result(res):
    print(f"\nRESULT {res['result']}: {res['reason']}")
    if "properties" not in res:         # the proof did not start
        return
    p, c, t = res["properties"], res["candidates"], res["times"]
    deferred = f", {c['standby']} of {c['deferred']} deferred never needed" if c["deferred"] else ""
    deferred += f", {c['pre_dropped']} dropped in an earlier run" if c["pre_dropped"] else ""
    print(f"properties {p['proven']}/{p['total']} proven ({len(p['timed_out'])} timed out); candidates "
          f"{c['proven']}/{c['total']} proven ({c['falsified_base']} falsified in base, {c['retracted']} "
          f"retracted, {c['timed_out']} timed out{deferred}); layers L0 {res['layer_counts']['0']} "
          f"L1 {res['layer_counts']['1']}; {res['restarts']} session restarts, {res['recycles']} memory rebuilds")
    print(f"sweeps {res['sweeps']}, checks {res['checks']}, queries {res['queries']}; times {t}")
    for what in ("falsified", "unproven"):
        for lab in p[what][:20]:
            print(f"  property {what}: {lab}")


def prove_within_limits(args, log):
    """prove(), ended with result UNKNOWN by --timeout or by a SIGTERM."""
    def on_alarm(signum, frame):
        raise Timeout

    def on_term(signum, frame):     # the solver sessions have their own process groups
        raise Timeout(f"terminated by signal {signum}")

    signal.signal(signal.SIGTERM, on_term)
    if args.timeout:
        signal.signal(signal.SIGALRM, on_alarm)
        signal.alarm(args.timeout)
    res = prove(args, log)
    signal.alarm(0)
    return res


def main():
    args = parse_args()
    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "checks.jsonl"), "w") as jsonl:
            def log(rec):
                jsonl.write(json.dumps(rec) + "\n")
                jsonl.flush()

            res = prove_within_limits(args, log)
        with open(os.path.join(args.out, "summary.json"), "w") as fh:
            json.dump(res, fh, indent=1)
    else:
        res = prove_within_limits(args, None)
    print_result(res)
    sys.exit(EXIT[res["result"]])


if __name__ == "__main__":
    main()
