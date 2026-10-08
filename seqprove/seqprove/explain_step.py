#!/usr/bin/env python3
"""Why does an assert fail the step case? Reproduces the check and prints the counterexample around it.

usage: explain_step.py model.smt2 --candidates asserts.vh --assert IDX [--run RUN_DIR] [--state start|end]
                       [--k 2] [--solver boolector] [--scope-depth 0] [--max 60]

Hypotheses: all asserts, or with --run those live at the start (--state start) or end of that run. On sat
it prints, at steps K-1 and K: the registers the assert reads (R0), the named wires in their scope
(--scope-depth), and the registers of R0's next-state cone that no two-register hypothesis pins to a
partner. --trace instead slices the counterexample backwards (taken mux branches, controlling and/or
inputs) to the registers and inputs at step K-1. Diagnosis only.
"""
import argparse
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cone_gap
from model import Model, parse_first
from session import Session

VALUE = re.compile(r"(#b[01]+|#x[0-9a-fA-F]+|true|false)\s*\)")


def values(s, top, names, step):
    """Values of the named wires at a step, in request order (as Session.violated)."""
    out = []
    for c in range(0, len(names), 400):
        part = names[c:c + 400]
        terms = " ".join(f"(|{top}_n {n}| s{step})" for n in part)
        vals = VALUE.findall(s.cmd(cmd="smtlib", command=f"(get-value ({terms}))", response=True))
        if len(vals) != len(part):
            sys.exit(f"get-value: expected {len(part)} values, got {len(vals)}")
        out += vals
    return dict(zip(names, out))


def short(v):
    if v in ("true", "false"):
        return "1" if v == "true" else "0"
    if v.startswith("#b") and len(v) > 34:
        return f"{len(v) - 2}'h{int(v.removeprefix('#b'), 2):x}"
    return v[2:] if v.startswith("#b") else "h" + v[2:]


class Tracer:
    """Dynamic slice: which sub-terms gave a bit its value, with values from the solver at a step."""

    def __init__(self, s, top, m, names, K, budget, conds=False):
        self.s, self.top, self.m, self.names, self.K, self.left = s, top, m, names, K, budget
        self.conds = conds
        self.cache, self.seen = {}, set()
        self.wire_of = {}                  # def id -> a wire name defined as a plain call of it
        for w, line in m["wires"].items():
            b = cone_gap.body(line)
            mm = re.fullmatch(r"\(\|\S+?#(\d+)\| state\)", b)
            if mm:
                n = int(mm.group(1))
                if n not in self.wire_of or len(w) < len(self.wire_of[n]):
                    self.wire_of[n] = w

    def describe(self, t):
        """Short name of a term: its wire or register name if it is a plain call, else its operator."""
        seen = 0
        while isinstance(t, list) and seen < 50:
            seen += 1
            if len(t) == 2 and t[1] == "state" and isinstance(t[0], str) and "#" in t[0]:
                n = int(t[0].strip("|").split("#")[1])
                if n in self.m["decl"]:
                    return self.names.get(n) or self.m["decl"][n]
                if n in self.wire_of:
                    return self.wire_of[n]
                t = parse_first(cone_gap.body(self.m["defs"][n]))
                if isinstance(t, list) and (t[0] in ("ite", "not") or (t[0] == "=" and isinstance(t[-1], str))):
                    t = t[1] if t[0] != "ite" or all(isinstance(x, str) for x in t[2:]) else t
                    if isinstance(t, list) and t[0] == "ite":
                        # reset mux in front of a register: ite(<input>, q, const)
                        arms = [x for x in t[2:] if isinstance(x, list)]
                        if len(arms) == 1:
                            t = arms[0]
                            continue
                        return f"#{n} (mux)"
                    continue
                return f"#{n} ({t[0] if isinstance(t, list) and isinstance(t[0], str) else 'op'})"
            return t[0] if isinstance(t[0], str) else "extract"
        return str(t)

    def smt(self, t, step):
        if isinstance(t, str):
            return f"s{step}" if t == "state" else t
        return "(" + " ".join(self.smt(x, step) for x in t) + ")"

    def val(self, t, step):
        """Value as a bit string, MSB first ("1"/"0" for Bool)."""
        if isinstance(t, str):
            if t in ("true", "false"):
                return "1" if t == "true" else "0"
            return t[2:] if t.startswith("#b") else f"{int(t.removeprefix('#x'), 16):b}".zfill(4 * (len(t) - 2))
        key = (self.smt(t, step), step)
        if key not in self.cache:
            r = self.s.cmd(cmd="smtlib", command=f"(get-value ({key[0]}))", response=True)
            v = VALUE.findall(r)
            if not v:
                sys.exit(f"get-value: no value in {r[:200]!r}")
            self.cache[key] = self.val(v[-1], step)
        return self.cache[key]

    def bit(self, t, i, step):
        v = self.val(t, step)
        return v[len(v) - 1 - i]

    def out(self, depth, text):
        self.left -= 1
        print("  " + "| " * min(depth, 30) + text, flush=True)

    def trace(self, t, i, step, depth=0):
        """Print where bit i of term t got its value at step, following the counterexample backwards."""
        if self.left <= 0:
            return
        if isinstance(t, str):
            self.out(depth, f"constant {t}")
            return
        head = t[0]
        if len(t) == 2 and t[1] == "state" and isinstance(head, str) and "#" in head:
            self._trace_symbol(t, i, step, depth)
        elif isinstance(head, list) and head[:2] == ["_", "extract"]:
            self.trace(t[1], i + int(head[3]), step, depth)
        elif head == "concat" and (part := self._concat_part(t, i, step)):
            self.trace(*part, step, depth)
        elif head == "ite":
            self._trace_mux(t, i, step, depth)
        elif head in ("not", "bvnot"):
            self.trace(t[1], i, step, depth)
        elif head in ("and", "bvand", "or", "bvor"):
            self._trace_and_or(t, i, step, depth)
        elif head == "=" and len(t) == 3 and isinstance(t[2], str) and len(self.val(t[1], step)) == 1:
            self.trace(t[1], 0, step, depth)
        else:
            self._trace_operands(t, i, step, depth)

    def _trace_symbol(self, t, i, step, depth):
        """t is `(|mod#N| state)`: an input ends the slice, a register at step K continues at K-1, a defined
        term continues with its body."""
        n = int(t[0].strip("|").split("#")[1])
        v = self.bit(t, i, step)
        if n in self.m["decl"]:
            kind = "register" if n in self.m["regs"] else "input"
            label = self.names.get(n) or self.m["decl"][n]
            self.out(depth, f"= {v}  {kind} {label} bit {i} at step {step}")
            if kind == "register" and step == self.K and (n, i) not in self.seen:
                self.seen.add((n, i))
                for nx in self.m["nxt"].get(n, []):     # "(= <next-state term> " of the transition
                    self.out(depth, f"   its next-state function at step {step - 1}:")
                    self.trace(parse_first(nx.strip()[2:].strip()), i, step - 1, depth + 1)
            return
        if (n, i, step) in self.seen:
            self.out(depth, f"= {v}  #{n} bit {i} (shown above)")
            return
        self.seen.add((n, i, step))
        if n in self.wire_of:
            self.out(depth, f"= {v}  wire {self.wire_of[n]} bit {i}")
        self.trace(parse_first(cone_gap.body(self.m["defs"][n])), i, step, depth)

    def _concat_part(self, t, i, step):
        """(operand, bit in it) of the concat t that holds bit i; the last operand is the lowest."""
        lo = 0
        for x in reversed(t[1:]):
            w = len(self.val(x, step))
            if i < lo + w:
                return x, i - lo
            lo += w
        return None

    def _trace_mux(self, t, i, step, depth):
        """The taken branch of an ite; its condition on one line, or sliced as well with conds."""
        if all(isinstance(x, str) for x in t[2:]):          # Bool <-> bit conversion
            self.trace(t[1], 0, step, depth)
            return
        c = self.val(t[1], step)
        taken, branch = (t[2], "then") if c == "1" else (t[3], "else")
        if not self.conds:              # data path only: the condition on one line
            self.out(depth, f"mux {branch}, condition {self.describe(t[1])} = {c}")
            self.trace(taken, i, step, depth)
            return
        self.out(depth, f"mux, condition = {c}:")
        self.trace(t[1], 0, step, depth + 1)
        self.out(depth, f"taken branch ({branch}):")
        self.trace(taken, i, step, depth + 1)

    def _trace_and_or(self, t, i, step, depth):
        """A controlling operand (a 0 of an and, a 1 of an or) explains the result alone: follow one of
        those; without one, every operand matters."""
        ctrl = "0" if t[0] in ("and", "bvand") else "1"
        v = self.bit(t, i, step)
        ops = [x for x in t[1:] if self.bit(x, i, step) == ctrl] if v == ctrl else t[1:]
        ops = sorted(ops, key=lambda x: isinstance(x, str))[:1 if v == ctrl else None]
        for x in ops:
            self.trace(x, i, step, depth)

    def _trace_operands(self, t, i, step, depth):
        """Any other operator: its operand values on one line, then every operand."""
        head = t[0]
        self.out(depth, f"= {self.bit(t, i, step)}  {head if isinstance(head, str) else 'op'} of "
                        + ", ".join(short('#b' + self.val(x, step)) for x in t[1:]))
        for x in t[1:]:
            if not isinstance(x, str):
                self.trace(x, i if head in ("bvxor", "xor") else 0, step, depth + 1)


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("smt2")
    ap.add_argument("--candidates", action="append", default=[])
    ap.add_argument("--assert", dest="idx", type=int, required=True)
    ap.add_argument("--run", help="seq_prove --out dir (checks.jsonl)")
    ap.add_argument("--state", choices=("start", "end"), default="start")
    ap.add_argument("--k", type=int, default=2)
    ap.add_argument("--solver", default="boolector")
    ap.add_argument("--scope-depth", type=int, default=0, help="go this many hierarchy levels up for the wires")
    ap.add_argument("--max", type=int, default=60, help="print at most this many wires / registers per list")
    ap.add_argument("--assume-smt", action="append", default=[], metavar="EXPR",
                    help="experiment: also assume this SMT-LIB Bool term at steps 0..K-1; {s} is the state, "
                         "{n:NAME} the wire NAME at that state, e.g. '(bvult {n:top.u.fmt_q} #b101)'")
    ap.add_argument("--guard-smt", metavar="EXPR",
                    help="experiment: check the guarded assert `EXPR -> assert` instead (same placeholders): "
                         "it is assumed at steps 0..K-1 and the goal is EXPR and not the assert at step K")
    ap.add_argument("--per-assert-hyps", action="store_true",
                    help="assume every hypothesis through its own literal, as seq_prove does (it has to "
                         "retract them one by one), instead of one conjunction per step: same query, "
                         "for timing")
    ap.add_argument("--trace", action="store_true", help="dynamic slice of the counterexample (see above)")
    ap.add_argument("--trace-nodes", type=int, default=400, help="stop the slice after this many nodes")
    ap.add_argument("--trace-conds", action="store_true", help="also slice the mux conditions")
    return ap.parse_args()


def hypotheses(mod, run, state):
    """The asserts assumed at steps 0..K-1: all, or those the run had not dropped (end) or not falsified in
    the base case (start); pre-dropped ones never were."""
    dropped = set()
    for r in cone_gap.run_records(run) if run else ():
        if r.get("event") == "drop" and (state == "end" or "base" in r["reason"]):
            dropped.add(r["id"])
        elif r.get("event") == "pre_drop":
            dropped.update(r["ids"])
    return sorted(set(mod.assert_loc) - dropped)


def unpaired_registers(m, hyps, regs):
    """Those of regs that no hypothesis relating exactly two registers pins to a partner."""
    paired = set()
    for i in hyps:
        rs = [r for r in cone_gap.support(m, [m["asserts"][i]], budget=64) or [] if r in m["regs"]]
        if len(rs) == 2:
            paired.update(rs)
    return regs - paired


def smt_at(expr, top, st):
    """An --assume-smt / --guard-smt expression at step st: its {s} and {n:NAME} placeholders filled in."""
    term = re.sub(r"\{n:([^}]+)\}", lambda mm: f"(|{top}_n {mm.group(1)}| s{st})", expr)
    return term.replace("{s}", f"s{st}")


def assume_hypotheses(s, a, hyps, top):
    """Steps 0..K of non-initial states, hypotheses (and extra terms) assumed at steps 0..K-1."""
    K = a.k
    s.setup_steps(K + 1, init=False)
    for st in range(K):
        if a.per_assert_hyps:
            for i in hyps:
                s.hyp(i, [st], True)
        else:
            s.assume_all(f"hyp{st}", hyps, st)
    for e in a.assume_smt:      # an experiment ("would this invariant help?"), never part of a proof
        for st in range(K):
            s.cmd(cmd="smtlib", command=f"(assert {smt_at(e, top, st)})")
        print(f"EXPERIMENT: additionally assumed at steps 0..{K - 1}: {e}", flush=True)
    if a.guard_smt:
        for st in range(K):
            s.cmd(cmd="smtlib", command=f"(assert (=> {smt_at(a.guard_smt, top, st)} (|{top}_a {a.idx}| s{st})))")
        print(f"EXPERIMENT: checking `{a.guard_smt} -> assert {a.idx}` (assumed at steps 0..{K - 1})",
              flush=True)


def step_check(s, a, top):
    """The step check of the assert (after a sanity check of the hypotheses); on sat the session holds the
    counterexample."""
    K = a.k
    t0 = time.time()
    r = s.plain_check()
    print(f"hypotheses without goal: {r} ({time.time() - t0:.1f}s)", flush=True)
    if r != "sat":
        sys.exit("the hypotheses are contradictory or undecided: every step check is vacuous with them")
    s.cmd(cmd="push")
    if a.guard_smt:
        s.cmd(cmd="smtlib", command=f"(assert {smt_at(a.guard_smt, top, K)})")
    s.cmd(cmd="assert", expr=["not", ["mod_a", a.idx, ["step", K]]])
    t0 = time.time()
    r = s.cmd(cmd="check")
    print(f"step check of assert {a.idx} at step {K}: {r} ({time.time() - t0:.1f}s)"
          + (" (inductive with these hypotheses)" if r == "unsat" else ""), flush=True)
    return r


def print_slice(s, a, m, top, name):
    """--trace: the dynamic slice of the failing assert."""
    tr = Tracer(s, top, m, name, a.k, a.trace_nodes, a.trace_conds)
    print(f"\nslice of assert {a.idx} at step {a.k} (it is false there):")
    tr.trace(parse_first(cone_gap.body(m["asserts"][a.idx])), 0, a.k)
    if tr.left <= 0:
        print(f"  ... stopped after {a.trace_nodes} nodes (--trace-nodes)")


def print_values(s, a, m, top, name, r0, unpaired):
    """R0, the wires in its scope and the unpinned R1 registers, with values at steps K-1 and K."""
    K = a.k

    def show(title, names):
        names = [n for n in names if n in m["wires"]]
        if not names:
            return
        v0, v1 = values(s, top, names, K - 1), values(s, top, names, K)
        print(f"\n{title} ({len(names)}), value at step {K - 1} -> step {K}:")
        for n in names[:a.max]:
            print(f"  {short(v0[n]):>20s} -> {short(v1[n]):<20s} {n}")
        if len(names) > a.max:
            print(f"  ... {len(names) - a.max} more")

    show("R0: registers the assert reads", sorted(name[r] for r in r0 if r in name))
    scopes = set()
    for r in r0:
        parts = name.get(r, "").split(".")
        if len(parts) > 1:
            scopes.add(".".join(parts[:max(1, len(parts) - 1 - a.scope_depth)]) + ".")
    local = sorted(w for w in m["wires"] if any(w.startswith(p) and "." not in w[len(p):] for p in scopes))
    show("named wires in the scope of R0", local)
    show("R1 registers without a two-register hypothesis", [name[r] for r in unpaired if r in name])
    anon = [r for r in unpaired if r not in name]
    if anon:
        print(f"\n{len(anon)} more such registers have no named wire: {[m['decl'].get(r, r) for r in anon[:8]]}")


def main():
    a = parse_args()
    K = a.k
    mod = Model(a.smt2, a.candidates)
    m = cone_gap.parse(a.smt2)
    hyps = hypotheses(mod, a.run, a.state)
    print(f"{len(mod.assert_loc)} asserts, {len(hyps)} hypotheses at steps 0..{K - 1} ({a.state} of the run)"
          if a.run else f"{len(hyps)} asserts, all hypotheses at steps 0..{K - 1}", flush=True)

    name = cone_gap.register_names(m)
    r0, r1 = cone_gap.cone(m, a.idx)
    unpaired = sorted(unpaired_registers(m, hyps, r1), key=lambda r: name.get(r, ""))
    print(f"assert {a.idx} ({m['loc'][a.idx]}): R0 {len(r0)} registers, R1 {len(r1)}, of those "
          f"{len(unpaired)} without a two-register hypothesis", flush=True)

    s = Session("explain", a.smt2, a.solver, mod.top, declare=a.solver == "boolector")
    try:
        assume_hypotheses(s, a, hyps, mod.top)
        if step_check(s, a, mod.top) != "sat":
            return
        if a.trace:
            print_slice(s, a, m, mod.top, name)
        else:
            print_values(s, a, m, mod.top, name, r0, unpaired)
    finally:
        s.kill()


if __name__ == "__main__":
    main()
