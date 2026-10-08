#!/usr/bin/env python3
"""Which registers in the cone of a property have no (surviving) candidate? Diagnoses UNKNOWN results.

usage: cone_gap.py model.smt2 --candidates asserts.vh [--run RUN_DIR] [--assert IDX ...] [--list N]

Per property: R0 (registers it reads at step K) and R1 (registers R0's next-state logic reads), split by
instance and by candidate coverage (live, step-retracted, timed out, dropped earlier, base-falsified, none).
A register in R1 without a live candidate is free in the step case unless other hypotheses pin it.
Registers are named by the wire in front of them (needs `write_smt2 -wires`). --run reads that run's
checks.jsonl; without it every candidate counts as live.
"""
import argparse
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from model import parse_first

REF = re.compile(r"\|(\S+?)#(\d+)\| state\b")


def parse(path):
    """The parts of the model the cone analysis needs, as raw text lines keyed by symbol number or name."""
    m = {"defs": {}, "decl": {}, "regs": set(), "wires": {}, "asserts": {}, "loc": {}, "nxt": {}}
    wire, in_t = None, False            # name from the preceding wire comment; inside |mod_t|
    with open(path) as fh:
        for ln in fh:
            if ln.startswith("; yosys-smt2-wire "):
                wire = ln.split()[2]
                continue
            if not (_read_comment(m, ln) or _read_symbol(m, ln, wire)):
                in_t = _read_transition(m, ln, in_t)
            wire = None
    return m


def _read_comment(m, ln):
    """Registers and assert locations from a `; yosys-smt2-*` comment. True if ln is one."""
    if ln.startswith("; yosys-smt2-witness "):
        w = json.loads(ln[len("; yosys-smt2-witness "):])
        if w.get("type") == "reg" and isinstance(w.get("smtname"), int):
            m["regs"].add(w["smtname"])
        return True
    if ln.startswith("; yosys-smt2-assert "):
        p = ln.split()
        m["loc"][int(p[2])] = p[4] if len(p) > 4 else ""
        return True
    return False


def _read_symbol(m, ln, wire):
    """Definitions and declarations of `|mod#N|` symbols, named wires and asserts. True if ln is one."""
    define = ln.startswith("(define-fun |")
    if not define and not ln.startswith("(declare-fun |"):
        return False
    sym = ln.split("|")[1]
    if "#" in sym:
        n = int(sym.split("#")[1])
        if define:
            m["defs"][n] = ln.split(" ; ")[0]
        else:
            m["decl"][n] = ln.split(" ; ", 1)[1].strip() if " ; " in ln else ""
    elif define and "_n " in sym and wire:
        m["wires"][wire] = ln.split(" ; ")[0]
    elif define and "_a " in sym:
        m["asserts"][int(sym.split("_a ")[1])] = ln.split(" ; ")[0]
    else:
        return False
    return True


def _read_transition(m, ln, in_t):
    """Next-state terms from the body of |mod_t|. Returns whether the next line is still inside it."""
    if ln.startswith("(define-fun |") and ln.split("|")[1].endswith("_t"):
        return True
    if in_t and ln.startswith("  (= "):
        # `(= <expr of state> (|mod#N| next_state))`: expr is the next state of register N
        mm = re.search(r"\(\|\S+?#(\d+)\| next_state\)\)", ln)
        if mm:
            m["nxt"].setdefault(int(mm.group(1)), []).append(ln[:mm.start()])
    return in_t and ln.startswith("  ")


def support(m, texts, budget=None):
    """Declared symbols (registers, inputs) the texts depend on combinationally."""
    seen, out, todo = set(), set(), []
    for t in texts:
        todo += [int(n) for _, n in REF.findall(t)]
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        if budget is not None and len(seen) > budget:
            return None
        if n in m["decl"]:
            out.add(n)
        elif n in m["defs"]:
            todo += [int(k) for _, k in REF.findall(m["defs"][n].split("))", 1)[1])]
    return out


def body(line):
    """Body of a one-line `(define-fun |x| ((state |s|)) SORT BODY)`."""
    rest = line.split("((state ", 1)[1].split("))", 1)[1].strip()
    if rest.startswith("Bool "):
        rest = rest[5:]
    elif rest.startswith("(_ BitVec"):
        rest = rest[rest.index(")") + 1:].strip()
    return rest[:-1].strip()


def regs_of(m, n, depth=0):
    """Registers a def is a plain copy of (see regs_of_term); None if it is other logic."""
    if n in m["regs"]:
        return [n]
    if n not in m["defs"] or depth > 50:
        return None
    b = body(m["defs"][n])
    return regs_of_term(m, parse_first(b), depth) if b.startswith("(") else None


def regs_of_term(m, t, depth=0):
    """Aliases, the async2sync reset mux, Bool views, extracts of one register and concats of those."""
    if not isinstance(t, list) or depth > 50:
        return None
    if len(t) == 2 and t[1] == "state" and isinstance(t[0], str) and "#" in t[0]:
        return regs_of(m, int(t[0].strip("|").split("#")[1]), depth + 1)
    if t[0] == "concat":
        out = []
        for x in t[1:]:
            r = regs_of_term(m, x, depth + 1)
            if r is None:
                return None
            out += r
        return out
    if t[0] == "ite" and len(t) == 4 and isinstance(t[1], list) and len(t[1]) == 2 and t[1][1] == "state":
        c = int(t[1][0].strip("|").split("#")[1])
        arms = [x for x in t[2:] if isinstance(x, list)]
        if c in m["decl"] and c not in m["regs"] and len(arms) == 1:
            return regs_of_term(m, arms[0], depth + 1)
        return None
    if t[0] == "=" and len(t) == 3 and t[2] == "#b1" and isinstance(t[1], list) and \
            isinstance(t[1][0], list) and t[1][0][:2] == ["_", "extract"] and t[1][0][2] == t[1][0][3]:
        return regs_of_term(m, t[1][1], depth + 1)
    if isinstance(t[0], list) and t[0][:2] == ["_", "extract"] and len(t) == 2:
        r = regs_of_term(m, t[1], depth + 1)
        return r if r is not None and len(r) == 1 else None
    return None


def register_names(m):
    """{register: the named wire in front of it (alias or async2sync reset mux)}; others are left out."""
    name = {}
    for w, line in m["wires"].items():
        b = body(line)
        rs = regs_of_term(m, parse_first(b)) if b.startswith("(") else None
        for r in rs or []:   # prefer a hierarchical name (instance.path) over miter-level copies
            if r not in name or ("." not in w, len(w)) < ("." not in name[r], len(name[r])):
                name[r] = w
    return name


def cone(m, idx):
    """(R0, R1) of an assert: the registers it reads, and the registers their next-state logic reads."""
    regs = m["regs"]
    r0 = {r for r in support(m, [m["asserts"][idx]]) if r in regs}
    r1 = {r for r in support(m, [t for x in r0 for t in m["nxt"].get(x, [])]) if r in regs}
    return r0, r1


def run_records(run_dir):
    """The records of a run's checks.jsonl."""
    with open(os.path.join(run_dir, "checks.jsonl")) as fh:
        for ln in fh:
            try:
                yield json.loads(ln)
            except ValueError:      # last line of a killed run
                continue


def drop_kind(reason, ignore_step):
    if "base" in reason:
        return "base"
    if ignore_step:
        return "live"
    return "timeout" if "timed out" in reason or "timeout" in reason else "step"


def candidate_status(run_dir, ignore_step):
    """{assert: "live", "base", "step", "timeout" or "earlier"} from a run's drop events. All live without a run."""
    status = collections.defaultdict(lambda: "live")
    for r in run_records(run_dir) if run_dir else ():
        if r.get("event") == "drop":
            status[r["id"]] = drop_kind(r["reason"], ignore_step)
        elif r.get("event") == "pre_drop":      # --drop-from: never a hypothesis of this run
            status.update(dict.fromkeys(r["ids"], "earlier"))
    return status


def coverage(m, cand, status):
    """({register: [status of each candidate that reads it]}, candidates without a register in a small
    cone)."""
    cov = collections.defaultdict(list)
    unresolved = 0
    for i in cand:
        rs = [r for r in support(m, [m["asserts"][i]], budget=64) or [] if r in m["regs"]]
        unresolved += not rs
        for r in rs:
            cov[r].append(status[i])
    return cov, unresolved


KINDS = ["live", "only step-retracted", "only timed out", "only dropped earlier", "only base-falsified",
         "no candidate"]


def klass(statuses):
    """Coverage class of a register: the best status among its candidates."""
    for status, kind in zip(("live", "step", "timeout", "earlier", "base"), KINDS):
        if status in statuses:
            return kind
    return "no candidate"


def report_property(m, p, name, kind_of, status, top_n):
    def group(r):
        return name[r].split(".")[0] if "." in name[r] else "(top/unnamed)"

    r0, r1 = cone(m, p)
    print(f"\n=== property {p} ({m['loc'][p]}, status {status[p]}): R0 {len(r0)} registers, R1 {len(r1)}")
    for tag, rs in (("R0", r0), ("R1", r1)):
        tab = collections.Counter((group(r), kind_of(r)) for r in rs)
        for g in sorted({g for g, _ in tab}):
            print(f"  {tag} {g:16s} " + "  ".join(f"{k}: {tab[(g, k)]}" for k in KINDS))
    gaps = collections.Counter()
    for r in r0 | r1:
        if kind_of(r) != "live":
            gaps[(re.sub(r"\[\d+\]$", "", name[r]), kind_of(r))] += 1
    if gaps:
        print(f"  registers without a live candidate (by name, {len(gaps)} groups), most frequent first:")
        for (n, k), c in gaps.most_common(top_n):
            print(f"    {c:5d}  {k:20s} {n}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("smt2")
    ap.add_argument("--candidates", action="append", default=[], help="candidate file basename(s)")
    ap.add_argument("--run", help="seq_prove --out dir (checks.jsonl with drop events)")
    ap.add_argument("--assert", dest="asserts", type=int, action="append", default=[],
                    help="property index (default: all non-candidate asserts)")
    ap.add_argument("--list", type=int, default=25, help="list this many uncovered register groups")
    ap.add_argument("--ignore-step", action="store_true",
                    help="count step-retracted candidates as live: coverage relative to all candidates that "
                         "survived the base case (what the first step checks assumed)")
    a = ap.parse_args()

    m = parse(a.smt2)
    cand = {i for i, loc in m["loc"].items() if os.path.basename(loc.split(":")[0]) in a.candidates}
    props = a.asserts or sorted(set(m["loc"]) - cand)
    print(f"{len(m['defs'])} defs, {len(m['regs'])} registers, {len(m['loc'])} asserts "
          f"({len(cand)} candidates), {len(m['nxt'])} registers with a next-state function", flush=True)

    name = register_names(m)
    for r in m["regs"]:
        name.setdefault(r, m["decl"].get(r, f"#{r}"))
    print(f"{sum(1 for r in m['regs'] if not name[r].startswith('$'))} registers named via wires", flush=True)

    status = candidate_status(a.run, a.ignore_step)
    cov, unresolved = coverage(m, cand, status)
    print(f"candidates: {collections.Counter(status[i] for i in cand)}; {unresolved} without a register "
          f"in a small cone (not counted)", flush=True)
    for p in props:
        report_property(m, p, name, lambda r: klass(cov.get(r, [])), status, a.list)


if __name__ == "__main__":
    main()
