#!/usr/bin/env python3
"""Prove the asserts of a miter one after another with yosys-smtbmc --incremental.

usage: seq_prove.py design.smt2 [--k K] [--solver S] [--src asserts.vh]
                     [--order index|reverse|colmajor|random] [--chunk N] [--goal push|assume]

Two smtbmc sessions:
  base : from the initial state, checks candidate i at steps 0..K-1 (own push/pop each)
  step : from an arbitrary state, assumes every already PROVEN assert at steps 0..K-1
         and checks candidate i at step K  (k-induction with proven lemmas)
Register equalities depend on each other cyclically, so one candidate is never inductive
on its own. Hence (Houdini): every live candidate is a *retractable* hypothesis (an SMT
assumption literal set with update_assumptions) at steps 0..K-1 of the step session.
Candidates are checked one after another; a candidate that fails is retracted at once and
the sweep restarts until a full sweep retracts nothing. The survivors are then jointly
k-inductive, and (with the base case) PROVEN. A base-case failure is a real counterexample.
"""
import argparse, json, os, re, subprocess, time

ap = argparse.ArgumentParser()
ap.add_argument("smt2")
ap.add_argument("--k", type=int, default=1)
ap.add_argument("--solver", default="z3")
ap.add_argument("--declare", action="store_true", help="bind hypotheses with declare-const + assert(=) instead of define-const (boolector)")
ap.add_argument("--src", action="append", default=[], help="file the assert locations point into, for readable names")
ap.add_argument("--order", default="index", choices=["index", "reverse", "colmajor", "random"],
                help="order in which candidates are checked (colmajor: by grid column, then row, then bit)")
ap.add_argument("--seed", type=int, default=0, help="seed for --order random")
ap.add_argument("--chunk", type=int, default=1,
                help="check N candidates with one query (disjunction of negations); on sat fall back to one by one")
ap.add_argument("--goal", default="push", choices=["push", "assume"],
                help="push: assert the negated goal inside push/pop; assume: pass it as a check-sat-assuming "
                     "literal so learned clauses survive between checks")
ap.add_argument("--model", action="store_true",
                help="on sat, read the model and drop EVERY live candidate it violates (not only the checked ones)")
args = ap.parse_args()
here = os.path.dirname(os.path.abspath(__file__))


class Session:
    def __init__(self):
        self.defs = {}
        env = dict(os.environ, PYTHONPATH=os.path.join(here, "..", "seqprove", "vendor"))
        self.p = subprocess.Popen(["yosys-smtbmc", "-s", args.solver, "--incremental", args.smt2],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env)

    def cmd(self, **c):
        self.p.stdin.write(json.dumps(c) + "\n"); self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("smtbmc exited")
            try:
                r = json.loads(line)
            except ValueError:
                raise RuntimeError(f"non-JSON line from smtbmc after {c}: {line!r}")
            if "msg" in r:
                continue
            if "err" in r:
                raise RuntimeError(f"{c}: {r['err']}")
            return r["ok"]

    def step(self, n, init):
        self.cmd(cmd="new_step", step=n)
        self.cmd(cmd="assert_design_assumes", step=n)
        self.cmd(cmd="assert", expr=["mod_h", ["step", n]])
        if init and n == 0:
            self.cmd(cmd="assert", expr=["mod_i", ["step", 0]])
            self.cmd(cmd="assert", expr=["mod_is", ["step", 0]])
        else:
            if n > 0:
                self.cmd(cmd="assert", expr=["mod_t", ["step", n - 1], ["step", n]])
            self.cmd(cmd="assert", expr=["not", ["mod_is", ["step", n]]])

    def falsify(self, idxs, step, probe=None):
        """True if some assert in idxs can be violated at `step` (sat).
        probe=(cands, steps): on sat, self.last_false = the cands the model violates at any of steps."""
        self.t_check = getattr(self, "t_check", 0.0)
        t0 = time.time()
        if args.goal == "push":
            neg = ["or"] + [["not", ["mod_a", i, ["step", step]]] for i in idxs]
            self.cmd(cmd="push")
            self.cmd(cmd="assert", expr=neg)
            r = self.cmd(cmd="check")
            if r == "sat" and probe:
                self.last_false = self.violated(*probe)
            self.cmd(cmd="pop")
        else:
            self.cmd(cmd="update_assumptions", key=["goal"], expr=self.goal_lit(idxs, step))
            r = self.cmd(cmd="check")
            if r == "sat" and probe:
                self.last_false = self.violated(*probe)
            self.cmd(cmd="update_assumptions", key=["goal"], expr=None)
        self.t_check += time.time() - t0
        return r == "sat"

    def violated(self, cands, steps):
        # values come back in request order (smtbmc may rename the terms, e.g. UNROLL#n for boolector)
        req = [(i, st) for i in cands for st in steps]
        terms = " ".join(f"(|{self.top}_a {i}| s{st})" for i, st in req)
        resp = self.cmd(cmd="smtlib", command=f"(get-value ({terms}))", response=True)
        vals = re.findall(r"\s(true|false)\s*\)", resp)
        if len(vals) != len(req):
            raise RuntimeError(f"get-value: expected {len(req)} values, got {len(vals)}")
        return {i for (i, _), v in zip(req, vals) if v == "false"}

    def goal_lit(self, idxs, step):
        # fresh Boolean symbol <-> OR of negated asserts; definitional, so it may stay in the solver
        self.ngoal = getattr(self, "ngoal", 0) + 1
        if args.declare:
            name = f"|goal {self.ngoal}|"
            body = " ".join(f"(not (|{self.top}_a {i}| s{step}))" for i in idxs)
            self.cmd(cmd="smtlib", command=f"(declare-const {name} Bool)")
            self.cmd(cmd="smtlib", command=f"(assert (= {name} (or false {body})))")
            return ["smtlib", name, "Bool"]
        neg = ["or"] + [["not", ["mod_a", i, ["step", step]]] for i in idxs]
        return ["def", self.cmd(cmd="define", expr=neg)["name"]]

    def hyp(self, idx, steps, on):
        # bitwuzla only takes Boolean symbols in check-sat-assuming, so bind each hypothesis to a define-const
        for s in steps:
            if on:
                if (idx, s) not in self.defs:
                    if args.declare:
                        name = f"|hyp {idx} {s}|"
                        self.cmd(cmd="smtlib", command=f"(declare-const {name} Bool)")
                        self.cmd(cmd="smtlib", command=f"(assert (= {name} (|{self.top}_a {idx}| s{s})))")
                        self.defs[(idx, s)] = name
                    else:
                        self.defs[(idx, s)] = self.cmd(cmd="define", expr=["mod_a", idx, ["step", s]])["name"]
                expr = ["smtlib", self.defs[(idx, s)], "Bool"] if args.declare else ["def", self.defs[(idx, s)]]
            else:
                expr = None
            self.cmd(cmd="update_assumptions", key=["h", idx, s], expr=expr)


base, stepper = Session(), Session()
K = args.k
for n in range(K):
    base.step(n, init=True)
for n in range(K + 1):
    stepper.step(n, init=False)

descs = base.cmd(cmd="modinfo", fields=["asserts"])["asserts"]
base.top = stepper.top = next(iter(descs)).rsplit("_a ", 1)[0]      # {"top_a 3": "$94 asserts.vh:32.7-32.50"}
names = {}
srclines = {os.path.basename(f): open(f).read().split("\n") for f in args.src}
for fn, d in descs.items():
    idx = int(fn.rsplit(" ", 1)[1])
    m = re.search(r"(\S+):(\d+)\.\d+-\d+\.\d+", d)
    label = d
    if m and m.group(1) in srclines:
        label = srclines[m.group(1)][int(m.group(2)) - 1].strip()
        label = re.sub(r"^assert\((.*)\);$", r"\1", label)
    names[idx] = label
todo = sorted(names)
if args.order == "reverse":
    todo.reverse()
elif args.order == "random":
    import random
    random.Random(args.seed).shuffle(todo)
elif args.order == "colmajor":
    def gridkey(i):
        m = re.search(r"reg(\d+)x(\d+)_a\[(\d+)\]", names[i])
        return (int(m.group(2)), int(m.group(1)), int(m.group(3))) if m else (1 << 30, 0, i)
    todo.sort(key=gridkey)
print(f"{len(todo)} candidate asserts, k={K}, solver={args.solver}, order={args.order}, "
      f"chunk={args.chunk}, goal={args.goal}")

live = list(todo)
for idx in live:
    stepper.hyp(idx, range(K), True)
failed, sweeps, checks = {}, 0, 0
t_all = time.time()
def check_one(idx):
    """None if idx survives, else the reason it is dropped."""
    if any(base.falsify([idx], j) for j in range(K)):
        return "FALSIFIED in base case"
    if stepper.falsify([idx], K):
        return "step case fails (retracted)"
    return None

def drop(idxs, reason, t0):
    global removed
    for idx in idxs:
        live.remove(idx)
        stepper.hyp(idx, range(K), False)
        failed[idx] = reason
        removed += 1
        print(f"sweep {sweeps}: {names[idx]:45s} {reason} ({time.time()-t0:.2f}s)")

def check_chunk_model(chunk):
    """Check chunk until it is unsat; each sat model drops every live candidate it violates."""
    global checks
    pending = list(chunk)
    while pending:
        t0 = time.time()
        checks += 1
        for j in range(K):
            if base.falsify(pending, j, probe=(live, range(K))):
                bad = base.last_false & set(live)
                reason = "FALSIFIED in base case"
                break
        else:
            if not stepper.falsify(pending, K, probe=(live, [K])):
                return
            bad = stepper.last_false & set(live)
            reason = "step case fails (retracted)"
        if not bad & set(pending):
            raise RuntimeError(f"sat model violates none of {pending}")
        drop(sorted(bad), reason, t0)
        pending = [i for i in pending if i in live]

while True:
    sweeps += 1
    removed = 0
    order = list(live)
    for c in range(0, len(order), args.chunk):
        chunk = [i for i in order[c:c + args.chunk] if i in live]
        if args.model:
            check_chunk_model(chunk)
            continue
        if len(chunk) > 1:
            checks += 1
            if not any(base.falsify(chunk, j) for j in range(K)) and not stepper.falsify(chunk, K):
                continue
        for idx in chunk:
            t0 = time.time()
            reason = check_one(idx)
            checks += 1
            if reason is None:
                continue
            live.remove(idx)
            stepper.hyp(idx, range(K), False)
            failed[idx] = reason
            removed += 1
            print(f"sweep {sweeps}: {names[idx]:45s} {reason} ({time.time()-t0:.2f}s)")
    print(f"sweep {sweeps}: removed {removed}, {len(live)} live")
    if not removed:
        break

print(f"\nPROVEN {len(live)}/{len(names)} (jointly {K}-inductive), refuted {len(failed)}, "
      f"{sweeps} sweeps, {checks} solver checks, {time.time()-t_all:.1f}s "
      f"(base {getattr(base, 't_check', 0):.1f}s, step {getattr(stepper, 't_check', 0):.1f}s)")
for idx, why in failed.items():
    print(f"  not proven: {names[idx]}  [{why}]")
for s in (base, stepper):
    s.p.stdin.close(); s.p.wait()
