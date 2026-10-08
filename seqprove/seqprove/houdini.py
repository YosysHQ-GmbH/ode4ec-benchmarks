"""Houdini k-induction over the asserts of a miter model, with layered step checks.

Properties (the miter's asserts) decide PASS/FAIL. Candidates (generated internal equalities) only help make
them inductive. The loop treats both the same way.

The base session checks every assert at steps 0..B-1 from the initial state (B = K, or K+1 if $initstate is
read). The step session unrolls K+1 non-initial states, assumes every live assert at steps 0..K-1 and checks
at step K. Layer 0 holds predicates over register reads only, layer 1 everything else. Layer-1 checks also
assume the live layer-0 asserts at step K.

Soundness. The loop ends after a sweep that drops nothing. For the final live set L = L0 + L1, with T the
transition relation over non-initial s0..sK:
    (A) a in L0:  T and L(s0..s_{K-1})             => a(sK)
    (B) b in L1:  T and L(s0..s_{K-1}) and L0(sK)  => b(sK)
and the base case holds for L at steps 0..B-1. Induction on the depth d of a reachable state: d < B is the
base case. Otherwise L holds on s_{d-K}..s_{d-1}, (A) gives L0 at s_d and then (B) gives L1. This is not
circular because layer-0 checks assume nothing at step K. The window is a step-session path, whose only init
constraint is `not _is` at every step. That holds for d > K. For d = K only the flag of s0 differs, and no
logic reads it unless $initstate is used, in which case B = K+1 covers d = K.

Any other way an assert leaves the live set is a retraction. A retraction only removes hypotheses, so it is
sound. Only a base-case failure is a counterexample. The options that retract (see README.md):
  --query-timeout, --timeout-siblings: an assert that times out is retracted, with --timeout-siblings also
    the other bits of its register. It is never reported as falsified.
  --drop-from: start without the candidates an earlier run dropped by a counterexample before its first
    timeout. Until that point its live set contained the greatest inductive set, so nothing is lost.
  --resume-from: start without everything an unfinished run retracted. This can lose a proof that needed one
    of them. check_last only changes the order.
  --defer-implied: a guarded equality implied by its live bit equalities waits on standby and is not used.
    When one of those bits drops, it is woken: its base case is checked first, because a false candidate would
    make the step hypotheses contradictory. Then it is assumed right away, because a check in between could
    retract an assert that is only inductive with it. Every wake follows a drop, so the final sweep still
    checks every live assert.
"""
import random
import re
import time

from model import ModelError
from session import QueryTimeout, Session, SessionError

BASE_FAIL = "falsified in base case"
STEP_FAIL = "step case fails (retracted)"
TIMEOUT_FAIL = "query timeout (retracted)"
TIMEOUT_SIBLING = "retracted: a bit of the same register timed out"
TIMED_OUT = (TIMEOUT_FAIL, TIMEOUT_SIBLING)
PRE_DROP = "dropped in an earlier run"
SESSION_ATTR = {"base": "base", "step": "step", "wide": "wstep"}   # Session.name -> Prover attribute


class Timeout(Exception):
    pass


class VacuityError(Exception):
    pass


class Prover:
    def __init__(self, model, k=1, solver="yices", declare=False, chunk=1, goal="push", use_model=False,
                 layers="auto", order="index", seed=0, labels=None, log=None, echo=print,
                 wide_bits=0, wide_solver=None, query_timeout=None, timeout_siblings=False, sibling_max=128,
                 session_mem_mb=None, defer_implied=False, pre_drop=(), check_last=()):
        self.m, self.k, self.solver, self.declare = model, k, solver, declare
        self.query_timeout = query_timeout or None
        self.timeout_siblings = timeout_siblings
        self.sibling_max = sibling_max
        self.hard_groups = set()        # groups with a timed-out assert
        self.hard_chunk = set()         # the same for groups wider than sibling_max, current chunk only
        self.group_size = {}
        self.restarts = 0
        self.session_mem_mb = session_mem_mb or None
        self.recycles = 0
        self.l0K_on = False             # step sessions assume layer 0 at step K
        self.chunk, self.goal, self.use_model, self.layers = chunk, goal, use_model, layers
        self.labels = labels or {}
        self.log, self.echo = log, echo
        self.all = self._ordered(model, order, seed)
        if check_last:
            last = set(check_last)
            self.all.sort(key=lambda i: i in last)
        self.layer = {i: (model.layer_of(i) if layers == "auto" else 0) for i in self.all}
        for i in self.all if timeout_siblings else ():
            g = self._group(i)
            self.group_size[g] = self.group_size.get(g, 0) + 1
        # wide asserts are checked one at a time in a step session of wide_solver
        self.wide_solver = wide_solver if wide_bits and wide_solver else None
        self.wide = {i for i in self.all if model.width_of(i) >= wide_bits} if self.wide_solver else set()
        # --defer-implied. wakes: assert -> the standby asserts it covers. queued: woken, not active yet.
        # woken: live since this layer pass, step check still due.
        self.standby, self.wakes, self.queued, self.woken = set(), {}, set(), []
        if defer_implied:
            self._defer_implied()
        self.n_standby = len(self.standby)
        self.live = set(self.all) - self.standby
        self.failed = {}
        self._take_over_drops(pre_drop)
        self.sweeps = self.checks = 0
        self.sanity = {}
        self.base = self.step = self.wstep = None
        # B in the soundness argument
        self.base_steps = k + 1 if model.uses_initstate else k
        self.done = False               # fixpoint reached
        self.t0 = time.time()

    @staticmethod
    def _ordered(model, order, seed):
        ids = sorted(model.assert_loc)
        if order == "reverse":
            ids.reverse()
        elif order == "random":
            random.Random(seed).shuffle(ids)
        elif order == "values-first":
            # A wrong value constraint over-constrains the step case until it is dropped, so check those
            # first. Every order is sound and reaches the same fixpoint.
            ids.sort(key=model.is_pair_equality)
        return ids

    def _defer_implied(self):
        """Put the candidates that other asserts imply on standby."""
        by_label = {}
        for i in self.all:
            if i in self.labels:
                by_label.setdefault(self.labels[i], []).append(i)
        for i in self.all:
            cover = self._cover(i, by_label) if self.m.is_candidate[i] else None
            if cover:
                self.standby.add(i)
                for j in cover:
                    self.wakes.setdefault(j, []).append(i)

    def _take_over_drops(self, pre_drop):
        """Start with the candidates in pre_drop dropped."""
        pre = [i for i in pre_drop if self.m.is_candidate.get(i)]
        for i in sorted(pre, key=lambda i: i not in self.standby):  # standby ones first: none is woken below
            self.standby.discard(i)
            self.live.discard(i)
            self.failed[i] = PRE_DROP
            for d in self.wakes.pop(i, ()):
                if d in self.standby:
                    self.standby.discard(d)
                    self.queued.add(d)

    def label(self, i):
        return self.labels.get(i) or self.m.assert_loc.get(i, str(i))

    def event(self, kind, **kw):
        if self.log:
            self.log(dict(event=kind, t=round(time.time() - self.t0, 3), **kw))

    def _on_check(self, rec):
        if self.log:
            self.log(dict(t=round(time.time() - self.t0, 3), **rec))

    def _steps(self):
        return [s for s in (self.step, self.wstep) if s]

    def _drop(self, idxs, reason, t0):
        K = self.k
        for i in idxs:
            if i not in self.live:
                continue
            self.live.discard(i)
            for s in self._steps():
                s.hyp(i, range(K), False)
            self.failed[i] = reason
            self.event("drop", id=i, reason=reason, layer=self.layer[i])
            self.echo(f"sweep {self.sweeps}: {self.label(i):45s} {reason} ({time.time() - t0:.2f}s)")
            for d in self.wakes.pop(i, ()):
                if d in self.standby:
                    self.standby.discard(d)
                    self.queued.add(d)
                    self.event("wake", id=d, by=i)

    def _activate(self):
        """Check the base case of the woken asserts, then assume them."""
        while self.queued:
            ids, t0 = sorted(self.queued), time.time()
            self.queued.clear()
            self.live.update(ids)           # not assumed yet
            try:
                for layer in (0, 1):
                    self._base_case_woken([i for i in ids if self.layer[i] == layer], layer, t0)
            except QueryTimeout as e:
                if not e.alive:
                    self._restart(e.session)
                self._drop(ids, TIMEOUT_FAIL, t0)
            for i in ids:
                if i in self.live:
                    for s in self._steps():
                        s.hyp(i, range(self.k), True)
                    self.woken.append(i)

    def _base_case_woken(self, pending, layer, t0):
        """Drop the asserts of pending that fail in the base case. With use_model, also drop every live
        assert a counterexample violates."""
        while pending:
            hit = self._base_sat(pending, layer, probe=self.use_model)
            if hit is None:
                return
            bad = sorted(hit[1] & self.live) if self.use_model else \
                [i for i in pending if self._base_sat([i], layer)]
            if not set(bad) & set(pending):
                raise SessionError(f"sat model violates none of {pending}")
            self._drop(bad, BASE_FAIL, t0)
            pending = [i for i in pending if i in self.live]

    def _cover(self, i, by_label):
        """For a label `G || (A[hi:lo] == B[hi:lo])`: the asserts `A[j] == B[j]`, j = lo..hi, else None."""
        m = re.fullmatch(r"\S+ \|\| \((\S+)\[(\d+):(\d+)\] == (\S+)\[(\d+):(\d+)\]\)", self.labels.get(i, ""))
        if not m or (m.group(2), m.group(3)) != (m.group(5), m.group(6)):
            return None
        cover = []
        for j in range(int(m.group(3)), int(m.group(2)) + 1):
            bits = by_label.get(f"{m.group(1)}[{j}] == {m.group(4)}[{j}]")
            if not bits:
                return None
            cover += bits
        return cover

    def _base_sat(self, idxs, layer, probe=False):
        """(step, violated asserts) for the first base-case step where an assert of idxs fails, else None."""
        for j in range(self.base_steps):
            sat, bad = self.base.falsify(idxs, j, self.goal, layer=layer,
                                         probe=(sorted(self.live), range(self.base_steps)) if probe else None)
            if sat:
                return j, bad
        return None

    def _step_sat(self, idxs, layer, probe=False, sess="step"):
        # A step model only refutes asserts checked under the same assumptions, so the probe drops asserts of
        # this layer only. A base-case model is a real trace and refutes everything it violates.
        same = sorted(i for i in self.live if self.layer[i] == layer)
        sat, bad = getattr(self, SESSION_ATTR[sess]).falsify(idxs, self.k, self.goal, layer=layer,
                                                             probe=(same, [self.k]) if probe else None)
        return (self.k, bad) if sat else None

    def fresh_session(self, name, solver_limit=True):
        """A new base, step or wide session. Step sessions get the current hypotheses."""
        K = self.k
        wide = name == "wide"
        s = Session(name, self.m.path, self.wide_solver if wide else self.solver, self.m.top,
                    (self.wide_solver == "boolector") if wide else self.declare, self._on_check,
                    self.query_timeout, solver_limit)
        if name == "base":
            s.setup_steps(self.base_steps, init=True)
        else:
            s.setup_steps(K + 1, init=False)
            for i in self.live:
                s.hyp(i, range(K), True)
            if self.l0K_on:
                s.assume_all("l0K", [i for i in self.live if self.layer[i] == 0], K)
        self._warm_up(s)
        return s

    def _warm_up(self, s):
        """With a per-check solver limit, run one unused check first so that loading the model does not count
        against the limit."""
        if s.solver_limit:
            t0 = time.time()
            r = s.plain_check()
            self.event("warm_up", session=s.name, result=r, secs=round(time.time() - t0, 3))

    def _plain_check(self, name, l0K=False):
        """check-sat without goal for the sanity checks. These need a definite answer, so a session with a
        per-check limit is replaced by a temporary one without (bitwuzla cannot lift the limit)."""
        s = getattr(self, SESSION_ATTR[name])
        tmp = self.fresh_session(name, solver_limit=False) if s.solver_limit else None
        use = tmp or s
        try:
            if l0K:
                use.assume_all("l0K", [i for i in self.live if self.layer[i] == 0], self.k)
            r = use.plain_check()
            if l0K:
                use.drop_all("l0K")
            return r
        finally:
            if tmp:
                tmp.kill()

    def _recycle(self, name):
        """Rebuild a session that grew past session_mem_mb, with the same hypotheses."""
        s = getattr(self, SESSION_ATTR[name])
        mb = s.rss_mb() if self.session_mem_mb else 0
        # at least 1.3x the fresh size, or a model bigger than the limit is rebuilt after every chunk
        if mb <= max(self.session_mem_mb or 0, 1.3 * getattr(s, "fresh_mb", 0)):
            return
        t0 = time.time()
        s.kill()
        new = self.fresh_session(name)
        new.fresh_mb = new.rss_mb()
        new.t_check, new.n_check = s.t_check, s.n_check
        setattr(self, SESSION_ATTR[name], new)
        self.recycles += 1
        self.event("recycle", session=name, rss_mb=round(mb), secs=round(time.time() - t0, 3))
        self.echo(f"sweep {self.sweeps}: {name} session rebuilt at {mb:.0f} MiB ({time.time() - t0:.1f}s)")

    def _restart(self, name):
        """Rebuild a session killed by a query timeout, with the current live hypotheses."""
        t0 = time.time()
        attr = SESSION_ATTR[name]
        old = getattr(self, attr)
        old.kill()
        new = self.fresh_session(name)
        new.t_check, new.n_check = old.t_check, old.n_check
        setattr(self, attr, new)
        self.restarts += 1
        self.event("restart", session=name, secs=round(time.time() - t0, 3))
        self.echo(f"sweep {self.sweeps}: {name} session rebuilt after a query timeout ({time.time() - t0:.1f}s)")

    def _on_timeout(self, e, chunk, check, t0):
        """Rebuild the session if needed, then check the chunk's asserts one by one. A single assert that
        times out is retracted, and with timeout_siblings its group is marked as hard."""
        if not e.alive:
            self._restart(e.session)
        else:
            self.event("solver_timeout", session=e.session, ids=list(chunk))
        if len(chunk) == 1:
            self._drop(chunk, TIMEOUT_FAIL, t0)
            self._activate()
            g = self._group(chunk[0]) if self.timeout_siblings else None
            if g:
                (self.hard_groups if self.group_size[g] <= self.sibling_max else self.hard_chunk).add(g)
            return
        for i in chunk:
            rest = self._retract_siblings([i]) if i in self.live else []
            if rest:
                check(rest)

    def _group(self, i):
        """The label without bit indices, or None. Guarded equalities `G || (E)` are grouped by E."""
        lab = self.labels.get(i)
        if not lab:
            return None
        m = re.fullmatch(r"\S+ \|\| \((.*)\)", lab)
        if m:
            return "guarded: " + m.group(1)
        return re.sub(r"\[\d+\]", "[]", lab) if re.search(r"\[\d+\]", lab) else None

    def _retract_siblings(self, chunk):
        """Retract the asserts whose group already timed out, without checking them."""
        hard = self.hard_groups | self.hard_chunk
        hit = [i for i in chunk if hard and self._group(i) in hard]
        if hit:
            self._drop(hit, TIMEOUT_SIBLING, time.time())
            self._activate()
        return [i for i in chunk if i in self.live]

    def _sweep_layer(self, cands, layer, sess="step", chunk_size=None):
        n = chunk_size or self.chunk
        for c in range(0, len(cands), n):
            self.hard_chunk.clear()
            chunk = self._retract_siblings([i for i in cands[c:c + n] if i in self.live])
            if chunk:
                (self._check_chunk_model if self.use_model else self._check_chunk)(chunk, layer, sess)
                if self.session_mem_mb:
                    self._recycle("base")
                    self._recycle(sess)

    def _check_chunk(self, chunk, layer, sess="step"):
        """Check the chunk in one query. If that is sat, check each assert alone."""
        t0 = time.time()
        try:
            if len(chunk) > 1:
                self.checks += 1
                if not self._base_sat(chunk, layer) and not self._step_sat(chunk, layer, sess=sess):
                    return
            for i in chunk:
                t0 = time.time()
                self.checks += 1
                if self._base_sat([i], layer):
                    self._drop([i], BASE_FAIL, t0)
                elif self._step_sat([i], layer, sess=sess):
                    self._drop([i], STEP_FAIL, t0)
                self._activate()
        except QueryTimeout as e:
            self._on_timeout(e, [i for i in chunk if i in self.live], lambda p: self._check_chunk(p, layer, sess), t0)

    def _check_chunk_model(self, chunk, layer, sess="step"):
        """Check the chunk until unsat. Each sat model drops every live assert it violates (classic Houdini)."""
        pending = list(chunk)
        while pending:
            t0 = time.time()
            self.checks += 1
            try:
                hit = self._base_sat(pending, layer, probe=True)
                reason = BASE_FAIL
                if hit is None:
                    hit = self._step_sat(pending, layer, probe=True, sess=sess)
                    reason = STEP_FAIL
                    if hit is None:
                        return
            except QueryTimeout as e:
                self._on_timeout(e, pending, lambda p: self._check_chunk_model(p, layer, sess), t0)
                return
            bad = hit[1] & self.live
            if not bad & set(pending):
                raise SessionError(f"sat model violates none of {pending}")
            self._drop(sorted(bad), reason, t0)
            self._activate()
            pending = [i for i in pending if i in self.live]

    def _houdini(self):
        """Sweep over the live asserts until a sweep drops nothing."""
        while True:
            self.sweeps += 1
            before = len(self.failed)
            for layer in (0, 1):
                cands = [i for i in self.all if i in self.live and self.layer[i] == layer]
                if cands:
                    self._layer_pass(cands, layer)
            removed = len(self.failed) - before
            self.echo(f"sweep {self.sweeps}: removed {removed}, {len(self.live)} live")
            self._log_sweep_sanity()
            if not removed:
                return

    def _layer_pass(self, cands, layer):
        """Check the live asserts of one layer and the asserts of that layer woken on the way. For layer 1
        the step sessions assume the live layer-0 asserts at step K."""
        t0 = time.time()
        if layer == 1:
            for s in self._steps():
                s.assume_all("l0K", [i for i in self.live if self.layer[i] == 0], self.k)
            self.l0K_on = True
        self.woken, todo = [], cands
        while todo:
            self._sweep_layer([i for i in todo if i not in self.wide], layer)
            wide = [i for i in todo if i in self.wide]
            if wide:
                self._sweep_layer(wide, layer, sess="wide", chunk_size=1)
            # woken asserts of this layer are checked now, the others in the next pass
            todo = [i for i in self.woken if i in self.live and self.layer[i] == layer]
            cands, self.woken = cands + todo, []
        if layer == 1:
            for s in self._steps():
                s.drop_all("l0K")
            self.l0K_on = False
        self.event("layer_done", sweep=self.sweeps, layer=layer, checked=len(cands),
                   secs=round(time.time() - t0, 3))

    def _log_sweep_sanity(self):
        """Warn if the step hypotheses are not sat. run() checks this again before the verdict."""
        r = self._plain_check("step")
        self.event("sanity", which=f"step_sweep_{self.sweeps}", result=r)
        if r != "sat":
            self.echo(f"WARNING: sweep {self.sweeps}: the step hypotheses without goal are {r}: "
                      "step checks under them prove nothing")

    def _sanity_step(self, when):
        """Non-vacuity: all live hypotheses plus live layer 0 at step K must be sat. Then every subset a later
        check uses is sat too."""
        r = self._plain_check("step", l0K=any(self.layer[i] == 1 for i in self.live))
        self.sanity[f"step_{when}"] = r
        self.event("sanity", which=f"step_{when}", result=r)
        return r == "sat"

    def run(self):
        """Run the proof and return the result (summary.json)."""
        m = self.m
        props = [i for i in self.all if not m.is_candidate[i]]
        cands = [i for i in self.all if m.is_candidate[i]]
        res = {"result": "ERROR", "reason": "", "smt2": m.path, "k": self.k, "solver": self.solver,
               "chunk": self.chunk,
               "goal": self.goal, "model": self.use_model, "layers": self.layers,
               "wide_solver": self.wide_solver, "wide": len(self.wide)}
        try:
            self._check_model(props, cands)
            self._open_sessions()
            sane_at_start = self._start()
            self._houdini()
            self.done = True
            if not sane_at_start and not self._sanity_step("end"):
                raise VacuityError(f"step-case hypotheses are {self.sanity['step_end']} without goal: "
                                   "contradictory, or not shown to be satisfiable")
            result, reason = self._verdict(props)
            res.update(result=result, reason=reason)
        except Timeout as e:
            res.update(result="UNKNOWN", reason=f"{e.args[0] if e.args else 'timeout'} after "
                                                f"{time.time() - self.t0:.0f}s")
        except VacuityError as e:
            res.update(result="ERROR", reason=f"vacuity: {e}")
        except (SessionError, ModelError) as e:
            res.update(result="ERROR", reason=str(e))
        finally:
            for s in (self.base, self.step, self.wstep):
                if s and res["result"] in ("PASS", "FAIL", "UNKNOWN") and "timeout" not in res["reason"]:
                    s.close()
                elif s:
                    s.kill()
        res.update(self._counts(props, cands))
        return res

    def _check_model(self, props, cands):
        """Refuse a model the method would be unsound or vacuous on, then print the setup."""
        m = self.m
        nets = m.clock_nets()
        if len(nets) > 1:
            raise ModelError(f"{len(nets)} distinct clock nets {list(nets.values())[:4]}: the one-step-per-"
                             "clock model without clk2fflogic is only sound for a single clock")
        if not props:
            raise VacuityError("no properties (every assert comes from a candidate file): nothing compared")
        if m.memories:
            self.echo(f"WARNING: {len(m.memories)} unmapped memories {m.memories[:3]}: "
                      "no candidates cover their contents")
        n0 = sum(1 for i in self.all if self.layer[i] == 0)
        self.echo(f"{len(self.all)} asserts ({len(props)} properties, {len(cands)} candidates), k={self.k}, "
                  f"solver={self.solver}, chunk={self.chunk}, goal={self.goal}, model={self.use_model}, "
                  f"layers={self.layers}: L0 {n0}, L1 {len(self.all) - n0}")

    def _open_sessions(self):
        """Open and unroll the base and step sessions, without hypotheses."""
        m, qt = self.m, self.query_timeout
        self.base = Session("base", m.path, self.solver, m.top, self.declare, self._on_check, qt)
        self.step = Session("step", m.path, self.solver, m.top, self.declare, self._on_check, qt)
        if self.wide:
            self.wstep = Session("wide", m.path, self.wide_solver, m.top, self.wide_solver == "boolector",
                                 self._on_check, qt)
            self.echo(f"{len(self.wide)} wide asserts checked alone with {self.wide_solver}: "
                      f"{[self.label(i)[:60] for i in sorted(self.wide)][:4]}")
        self.base.setup_steps(self.base_steps, init=True)
        for s in self._steps():
            s.setup_steps(self.k + 1, init=False)
        self.event("loaded", **{s.name: s.t_load for s in (self.base, *self._steps())})

    def _start(self):
        """Check that the base case is sat, then assume every live assert. Returns whether the step
        hypotheses are sat."""
        t0 = time.time()
        r = self._plain_check("base")
        self.sanity["base"] = r
        if r != "sat":
            raise VacuityError(f"base case without goal is {r}: " + (
                f"design assumptions/initial state admit no path of {self.base_steps} steps" if r == "unsat"
                else "no definite answer, so the assumptions are not shown to be satisfiable"))
        for i in self.all:
            if i in self.live:
                for s in self._steps():
                    s.hyp(i, range(self.k), True)
        pre = sorted(i for i, r in self.failed.items() if r == PRE_DROP)
        if pre:
            self.event("pre_drop", ids=pre)
            self.echo(f"{len(pre)} candidates start as dropped: taken over from an earlier run")
        self._activate()
        sane = self._sanity_step("start")
        for s in (self.base, *self._steps()):
            self._warm_up(s)
        self.event("setup_done", secs=round(time.time() - t0, 3))
        return sane

    def _verdict(self, props):
        """(result, reason) after the fixpoint, once the hypotheses are known to be sat."""
        falsified = [i for i in props if self.failed.get(i) == BASE_FAIL]
        if falsified:
            return "FAIL", f"{len(falsified)} properties falsified from the initial state"
        if all(i in self.live for i in props):
            return "PASS", "all properties proven"
        return "UNKNOWN", "some properties not inductive with the live candidates"

    def _counts(self, props, cands):
        m, sessions = self.m, [s for s in (self.base, self.step, self.wstep) if s]

        def cnt(ids, pred):
            return sum(1 for i in ids if pred(i))

        def why(i):
            return self.failed.get(i)

        return {
            "asserts": len(self.all),
            # before the fixpoint the live set proves nothing
            "properties": {"total": len(props), "proven": cnt(props, lambda i: i in self.live) if self.done else None,
                           "falsified": [self.label(i) for i in props if why(i) == BASE_FAIL],
                           "unproven": [self.label(i) for i in props if why(i) in (STEP_FAIL, *TIMED_OUT)],
                           "timed_out": [self.label(i) for i in props if why(i) in TIMED_OUT]},
            "candidates": {"total": len(cands), "proven": cnt(cands, lambda i: i in self.live) if self.done else None,
                           "falsified_base": cnt(cands, lambda i: why(i) == BASE_FAIL),
                           "retracted": cnt(cands, lambda i: why(i) == STEP_FAIL),
                           "timed_out": cnt(cands, lambda i: why(i) in TIMED_OUT),
                           "pre_dropped": cnt(cands, lambda i: why(i) == PRE_DROP),
                           # deferred: at the start, standby: never needed (neither counts as proven)
                           "deferred": self.n_standby, "standby": len(self.standby)},
            "query_timeout": self.query_timeout, "restarts": self.restarts, "timeout_siblings": self.timeout_siblings,
            "sibling_max": self.sibling_max, "session_mem_mb": self.session_mem_mb, "recycles": self.recycles,
            "base_steps": self.base_steps,
            "layer_counts": {str(L): cnt(self.all, lambda i, L=L: self.layer[i] == L) for L in (0, 1)},
            "sweeps": self.sweeps, "checks": self.checks, "sanity": self.sanity,
            "queries": {f"{s.name}_L{L}": n for s in sessions for L, n in s.n_check.items()},
            "times": dict(total=round(time.time() - self.t0, 2),
                       **{f"load_{s.name}": round(s.t_load or 0, 2) for s in sessions},
                       **{f"{s.name}_L{L}": round(t, 2) for s in sessions for L, t in s.t_check.items()}),
            "model_info": {"registers": len(m.registers), "clock_nets": len(m.clock_nets()),
                           "memories": len(m.memories), "uses_initstate": m.uses_initstate}}
