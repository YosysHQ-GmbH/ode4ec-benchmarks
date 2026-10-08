"""One `yosys-smtbmc --incremental` process (JSON command interface) holding an unrolled model."""
import contextlib
import json
import os
import re
import signal
import subprocess
import threading
import time
from collections import defaultdict

VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")


class SessionError(RuntimeError):
    pass


class QueryTimeout(SessionError):
    """A check ran over query_timeout. With alive, the solver stopped the check itself and the session is
    still usable. Otherwise the session was killed."""
    def __init__(self, name, secs, alive=False):
        super().__init__(f"{name}: query timeout after {secs}s")
        self.session, self.alive = name, alive


# Solvers with a per-check time limit: they answer `unknown` and the session stays usable. Given on the command
# line because bitwuzla ignores set-option after the first assertion.
PER_CHECK_LIMIT = {"bitwuzla": lambda ms: [f"--time-limit-per={ms}"]}


def has_check_limit(solver):
    return solver in PER_CHECK_LIMIT


class Session:
    def __init__(self, name, smt2, solver, top, declare=False, on_check=None, query_timeout=None,
                 solver_limit=True):
        """query_timeout: seconds per falsify() call. The solver enforces it if it can (PER_CHECK_LIMIT),
        otherwise a watchdog kills the session."""
        self.name, self.top, self.declare = name, top, declare
        self.smt2, self.solver = smt2, solver
        self.query_timeout = query_timeout
        self._expired = False
        self.solver_limit = bool(query_timeout and solver_limit and has_check_limit(solver))
        # falsify() only
        self.watchdog = 2 * query_timeout + 30 if self.solver_limit else query_timeout
        solver_args = PER_CHECK_LIMIT[solver](int(query_timeout * 1000)) if self.solver_limit else []
        self.on_check = on_check              # called with a dict per check (checks.jsonl)
        self.defs = {}                        # (idx, step) -> hypothesis literal
        self.extra = {}                       # key -> (frozenset(idxs), step, conjunction literal)
        self.nconj = 0
        self.t_check = defaultdict(float)     # per layer
        self.n_check = defaultdict(int)
        self.t_load = None
        pp = os.environ.get("PYTHONPATH")
        env = dict(os.environ, PYTHONPATH=VENDOR + (os.pathsep + pp if pp else ""))
        # own process group, so that a timeout kills the solver too
        extra = [a for arg in solver_args for a in ("-S", arg)]
        self.p = subprocess.Popen(["yosys-smtbmc", "-s", solver, *extra, "--noprogress", "--incremental", smt2],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env,
                                  start_new_session=True)

    def cmd(self, **c):
        try:
            self.p.stdin.write(json.dumps(c) + "\n")
            self.p.stdin.flush()
        except BrokenPipeError:
            raise SessionError(f"{self.name}: smtbmc exited (rc={self.p.poll()}) before {c.get('cmd')}") from None
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise SessionError(f"{self.name}: smtbmc exited (rc={self.p.wait()}) during {c.get('cmd')}")
            if line.startswith("##"):       # smtio progress line
                continue
            try:
                r = json.loads(line)
            except ValueError:
                raise SessionError(f"{self.name}: non-JSON line from smtbmc after {c.get('cmd')}: {line!r}") from None
            if "msg" in r:
                continue
            if "err" in r:
                raise SessionError(f"{self.name}: {c.get('cmd')}: {r['err']}")
            return r["ok"]

    def rss_mb(self):
        """Resident MiB of smtbmc and its solver, 0 without /proc."""
        pages = 0
        try:
            pids = [d for d in os.listdir("/proc") if d.isdigit()]
        except OSError:
            return 0
        for d in pids:
            try:
                with open(f"/proc/{d}/stat") as f:
                    pgrp = int(f.read().rsplit(")", 1)[1].split()[2])
                if pgrp == self.p.pid:
                    with open(f"/proc/{d}/statm") as f:
                        pages += int(f.read().split()[1])
            except (OSError, ValueError, IndexError):   # the process ended meanwhile
                continue
        return pages * os.sysconf("SC_PAGE_SIZE") / 2**20

    def close(self):
        try:
            self.p.stdin.close()
            self.p.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            self.kill()

    def kill(self):
        with contextlib.suppress(ProcessLookupError):
            os.killpg(self.p.pid, signal.SIGKILL)
        with contextlib.suppress(subprocess.TimeoutExpired):
            self.p.wait(timeout=10)

    def setup_steps(self, n, init):
        """Declare steps 0..n-1 with transitions and design assumptions. With init, step 0 is the initial
        state (base case). Otherwise every step is non-initial, as in smtbmc's tempind."""
        t0 = time.time()
        for s in range(n):
            self.cmd(cmd="new_step", step=s)
            if s == 0:
                self.t_load = time.time() - t0     # the first command waits until the model is loaded
            self.cmd(cmd="assert_design_assumes", step=s)
            self.cmd(cmd="assert", expr=["mod_h", ["step", s]])
            if init and s == 0:
                self.cmd(cmd="assert", expr=["mod_i", ["step", 0]])
                self.cmd(cmd="assert", expr=["mod_is", ["step", 0]])
            else:
                if s > 0:
                    self.cmd(cmd="assert", expr=["mod_t", ["step", s - 1], ["step", s]])
                self.cmd(cmd="assert", expr=["not", ["mod_is", ["step", s]]])

    def plain_check(self):
        """check-sat without goal."""
        return self.cmd(cmd="check")

    def _expire(self):
        self._expired = True
        self.kill()

    def falsify(self, idxs, step, goal="push", probe=None, layer=0):
        """(sat, bad). sat: some assert in idxs can be false at step. With probe=(cands, steps), bad is the
        set of cands the model violates at any of the steps."""
        if self._expired:
            raise QueryTimeout(self.name, self.query_timeout)
        timer = None
        if self.watchdog:
            timer = threading.Timer(self.watchdog, self._expire)
            timer.daemon = True
            timer.start()
        try:
            res = self._falsify(idxs, step, goal, probe, layer)
        except SessionError:
            if self._expired:
                raise QueryTimeout(self.name, self.query_timeout) from None
            raise
        finally:
            if timer:
                timer.cancel()
        if self._expired:    # the watchdog fired just after the answer
            raise QueryTimeout(self.name, self.query_timeout)
        return res

    def _falsify(self, idxs, step, goal, probe, layer):
        t0 = time.time()
        bad, t_probe = None, 0.0
        if goal == "push":
            self.cmd(cmd="push")
            self.cmd(cmd="assert", expr=["or"] + [["not", ["mod_a", i, ["step", step]]] for i in idxs])
            r = self.cmd(cmd="check")
            if r == "sat" and probe:
                tp = time.time()
                bad = self.violated(*probe)
                t_probe = time.time() - tp
            self.cmd(cmd="pop")
        else:
            self.cmd(cmd="update_assumptions", key=["goal"], expr=self._goal_lit(idxs, step))
            r = self.cmd(cmd="check")
            if r == "sat" and probe:
                tp = time.time()
                bad = self.violated(*probe)
                t_probe = time.time() - tp
            self.cmd(cmd="update_assumptions", key=["goal"], expr=None)
        dt = time.time() - t0
        self.t_check[layer] += dt
        self.n_check[layer] += 1
        if self.on_check:
            self.on_check({"session": self.name, "layer": layer, "step": step, "ids": list(idxs), "result": r,
                           "secs": round(dt, 4), "probe_secs": round(t_probe, 4)})
        if r == "unknown" and self.solver_limit:
            raise QueryTimeout(self.name, self.query_timeout, alive=True)
        if r not in ("sat", "unsat"):
            raise SessionError(f"{self.name}: solver answered {r!r}")
        return r == "sat", bad

    def violated(self, cands, steps):
        # match values by position: smtbmc may rename the terms (UNROLL#n for boolector)
        req = [(i, st) for i in cands for st in steps]
        terms = " ".join(f"(|{self.top}_a {i}| s{st})" for i, st in req)
        resp = self.cmd(cmd="smtlib", command=f"(get-value ({terms}))", response=True)
        vals = re.findall(r"\s(true|false)\s*\)", resp)
        if len(vals) != len(req):
            raise SessionError(f"{self.name}: get-value: expected {len(req)} values, got {len(vals)}")
        return {i for (i, _), v in zip(req, vals) if v == "false"}

    def _bind(self, terms, name):
        """A Boolean literal for the conjunction of terms (declare-const for boolector)."""
        body = terms[0] if len(terms) == 1 else "(and " + " ".join(terms) + ")"
        if self.declare:
            lit = f"|{name}|"
            self.cmd(cmd="smtlib", command=f"(declare-const {lit} Bool)")
            self.cmd(cmd="smtlib", command=f"(assert (= {lit} {body}))")
            return ["smtlib", lit, "Bool"]
        return ["def", self.cmd(cmd="define", expr=["smtlib", body, "Bool"])["name"]]

    def _goal_lit(self, idxs, step):
        self.nconj += 1
        neg = " ".join(f"(not (|{self.top}_a {i}| s{step}))" for i in idxs)
        return self._bind([f"(or false {neg})"], f"goal {self.nconj}")

    def hyp(self, idx, steps, on):
        """Assume assert idx at the given steps, or stop assuming it."""
        for s in steps:
            expr = None
            if on:
                if (idx, s) not in self.defs:
                    self.defs[(idx, s)] = self._bind([f"(|{self.top}_a {idx}| s{s})"], f"hyp {idx} {s}")
                expr = self.defs[(idx, s)]
            self.cmd(cmd="update_assumptions", key=["h", idx, s], expr=expr)

    def assume_all(self, key, idxs, step):
        """Assume every assert of idxs at step through one literal, rebound only when the set changes."""
        idxs = frozenset(idxs)
        cur = self.extra.get(key)
        if cur and cur[0] == idxs and cur[1] == step:
            lit = cur[2]
        elif not idxs:
            self.drop_all(key)
            return
        else:
            self.nconj += 1
            lit = self._bind([f"(|{self.top}_a {i}| s{step})" for i in sorted(idxs)], f"{key} {self.nconj}")
            self.extra[key] = (idxs, step, lit)
        self.cmd(cmd="update_assumptions", key=[key], expr=lit)

    def drop_all(self, key):
        self.cmd(cmd="update_assumptions", key=[key], expr=None)
