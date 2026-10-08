"""Reads a flattened yosys write_smt2 model: its asserts and which are candidates, registers, clock nets,
assert layers and widths. Uses only the `; yosys-smt2-*` annotations and one-line define-funs.
"""
import json
import os
import re

_TOKEN = re.compile(r"\(|\)|\|[^|]*\||[^\s()|;]+|;")
_ASSERT_LOC = re.compile(r"(\S+?):(\d+)\.\d+-\d+\.\d+")


class ModelError(Exception):
    pass


def parse_first(text):
    """First complete s-expression of `text` as nested token lists (iterative: concat chains nest deep)."""
    stack = [[]]
    for tok in _TOKEN.findall(text):
        if tok == ";" and len(stack) == 1:
            break
        if tok == "(":
            stack.append([])
        elif tok == ")":
            done = stack.pop()
            stack[-1].append(done)
            if len(stack) == 1:
                return done
        elif len(stack) > 1:
            stack[-1].append(tok)
    raise ModelError(f"unbalanced s-expression: {text[:120]}")


def _is_const(t):
    return isinstance(t, str) and (t.startswith(("#b", "#x")) or t in ("true", "false"))


def _is_bool_view(t):
    """(= x #b1) or (ite x #b1 #b0): yosys' conversions between Bool and (_ BitVec 1)."""
    if not isinstance(t, list):
        return False
    return (len(t) == 3 and t[0] == "=" and t[2] == "#b1") or \
        (len(t) == 4 and t[0] == "ite" and t[2:] == ["#b1", "#b0"])


class Model:
    def __init__(self, path, candidate_files=()):
        self.path = path
        self.modules = []
        self.registers = set()          # "miter#12", without bars
        self.declared = set()
        self.decl_width = {}
        self.defs = {}                  # "miter#12" -> define-fun line
        self.wires = {}                 # wire name -> define-fun line, short ones only (for clocks)
        self.clock_names = []
        self.memories = []
        self.assert_loc = {}            # idx -> "file:line.col-line.col"
        self.assert_line = {}           # idx -> define-fun |<mod>_a idx| line
        self.uses_initstate = False
        self._read()
        if len(self.modules) != 1:
            raise ModelError(f"model has {len(self.modules)} modules {self.modules[:5]}; it must be flattened, "
                             "otherwise asserts in submodules are not visible as top-level asserts")
        self.top = self.modules[0]
        cand = {os.path.basename(f) for f in candidate_files}
        self.is_candidate = {i: self.src_file(i) in cand for i in self.assert_loc}
        self._layer = {}

    def _read(self):
        with open(self.path) as fh:
            for line in fh:
                if line.startswith(";"):
                    self._read_comment(line)
                    continue
                # |<mod>_is| used anywhere but its declaration: the design reads $initstate
                if not self.uses_initstate and self.modules and f"|{self.modules[-1]}_is|" in line \
                        and not line.startswith(f"(declare-fun |{self.modules[-1]}_is|"):
                    self.uses_initstate = True
                if line.startswith("(define-fun |"):
                    self._read_define(line)
                elif line.startswith("(declare-fun |"):
                    self._read_declare(line)
        missing = set(self.assert_loc) - set(self.assert_line)
        if missing:
            raise ModelError(f"no single-line definition for asserts {sorted(missing)[:5]}")

    def _read_comment(self, line):
        if line.startswith("; yosys-smt2-module "):
            self.modules.append(line.split()[2])
        elif line.startswith("; yosys-smt2-witness "):
            w = json.loads(line[len("; yosys-smt2-witness "):])
            if w["type"] == "reg" and isinstance(w["smtname"], int):
                self.registers.add(f"{self.modules[-1]}#{w['smtname']}")
        elif line.startswith("; yosys-smt2-assert "):
            parts = line.split()
            self.assert_loc[int(parts[2])] = parts[4] if len(parts) > 4 else ""
        elif line.startswith("; yosys-smt2-clock "):
            self.clock_names.append(line.split()[2])
        elif line.startswith("; yosys-smt2-memory "):
            self.memories.append(line.split()[2])

    def _read_define(self, line):
        name = line[len("(define-fun |"):line.index("|", len("(define-fun |"))]
        if "#" in name and " " not in name:
            self.defs[name] = line
        elif name.startswith(f"{self.modules[-1]}_a "):
            self.assert_line[int(name.rsplit(" ", 1)[1])] = line
        elif line.startswith(f"(define-fun |{self.modules[-1]}_n ") and len(line) < 400:
            self.wires[name[len(self.modules[-1]) + 3:]] = line

    def _read_declare(self, line):
        sym = line[len("(declare-fun |"):line.index("|", len("(declare-fun |"))]
        self.declared.add(sym)
        w = self._sort_width(line)
        if w is not None:
            self.decl_width[sym] = w

    def src_file(self, idx):
        m = _ASSERT_LOC.search(self.assert_loc[idx])
        return os.path.basename(m.group(1)) if m else ""

    def src_line(self, idx):
        m = _ASSERT_LOC.search(self.assert_loc[idx])
        return int(m.group(2)) if m else None

    def _body(self, sym):
        form = parse_first(self.defs[sym])
        return form[4]

    def _call(self, t):
        """'miter#12' for (|miter#12| state), else None."""
        if isinstance(t, list) and len(t) == 2 and t[1] == "state" and isinstance(t[0], str) and t[0].startswith("|"):
            return t[0][1:-1]
        return None

    def _resolve(self, t):
        """Follow define-fun aliases whose body is a single call."""
        seen = 0
        while True:
            sym = self._call(t)
            if sym is None or sym not in self.defs or seen > 1000:
                return t
            t = self._body(sym)
            seen += 1

    def _is_input_read(self, t):
        """An input (declared, not a register), its negation, or its Bool view (= x #b1)."""
        t = self._resolve(t)
        if isinstance(t, list) and len(t) == 2 and t[0] == "not":
            t = self._resolve(t[1])
        if isinstance(t, list) and len(t) == 3 and t[0] == "=" and t[2] == "#b1":
            t = self._resolve(t[1])
            if isinstance(t, list) and len(t) == 2 and isinstance(t[0], list) and t[0][:2] == ["_", "extract"]:
                t = self._resolve(t[1])
        sym = self._call(t)
        return sym is not None and sym in self.declared and sym not in self.registers

    def is_register_read(self, t, need_register=False):
        """t only selects and concatenates register bits and constants, with need_register at least one
        register bit. Bool <-> BitVec 1 views and async2sync's reset mux ite(<input>, x, const) are accepted."""
        stack, found = [t], False
        while stack:
            t = stack.pop()
            if _is_const(t):
                continue
            sym = self._call(t)
            if sym is not None:
                if sym in self.registers:
                    found = True
                    continue
                if sym in self.defs:
                    stack.append(self._body(sym))
                    continue
                return False                                   # an input or an unknown symbol
            if not isinstance(t, list) or not t:
                return False
            head = t[0]
            if isinstance(head, list) and head[:2] == ["_", "extract"] and len(t) == 2:
                stack.append(t[1])
            elif head == "concat":
                stack.extend(t[1:])
            elif head == "ite" and len(t) == 4 and t[2] == "#b1" and t[3] == "#b0":
                stack.append(t[1])
            elif head == "ite" and len(t) == 4 and (_is_const(t[2]) != _is_const(t[3])) and \
                    self._is_input_read(t[1]):
                stack.append(t[3] if _is_const(t[2]) else t[2])
            elif head == "=" and len(t) == 3 and t[2] == "#b1":
                stack.append(t[1])
            else:
                return False
        return found or not need_register

    _PREDICATE_OPS = ("=", "distinct", "not", "and", "or", "xor", "=>", "ite")

    def is_state_predicate(self, t, budget=400):
        """t is made of comparisons and Boolean operators over register reads and constants, with at most
        budget operator nodes. E.g. `q_a == q_b`, `q != 3'd5`."""
        stack = [t]
        while stack:
            t = self._resolve(stack.pop())
            if self.is_register_read(t):
                continue
            budget -= 1
            if budget < 0 or not isinstance(t, list) or not t or t[0] not in self._PREDICATE_OPS:
                return False
            stack.extend(t[1:])
        return True

    def _condition(self, idx):
        """COND of an unconditional assert, which yosys writes as (or COND (not true)), else None."""
        body = parse_first(self.assert_line[idx])[4]
        if isinstance(body, list) and len(body) == 3 and body[0] == "or" and body[2] == ["not", "true"]:
            return self._resolve(body[1])
        return None

    def layer_of(self, idx):
        """0 for an unconditional state predicate, else 1. Soundness does not depend on the layer (see
        houdini.py); anything unusual goes to layer 1."""
        if idx not in self._layer:
            cond = self._condition(idx)
            self._layer[idx] = 0 if cond is not None and self.is_state_predicate(cond) else 1
        return self._layer[idx]

    def is_pair_equality(self, idx):
        """Equalities between register reads (`q_a == q_b`) or conjunctions of them."""
        cond = self._condition(idx)
        eqs = cond[1:] if isinstance(cond, list) and cond and cond[0] == "and" else [cond]
        eqs = [self._resolve(e) for e in eqs]
        return bool(eqs) and all(isinstance(e, list) and len(e) == 3 and e[0] == "=" and
                                 self.is_register_read(e[1], True) and self.is_register_read(e[2], True)
                                 for e in eqs)

    def _sort_width(self, line):
        """Width of the sort in a one-line declare-fun/define-fun: Bool -> 1, (_ BitVec N) -> N."""
        m = re.search(r"\(\(state \|[^|]+\|\)\) (Bool|\(_ BitVec (\d+)\))|\(\|[^|]+\|\) (Bool|\(_ BitVec (\d+)\))",
                      line)
        if not m:
            return None
        n = m.group(2) or m.group(4)
        return int(n) if n else 1

    def term_width(self, t):
        """Bit width of a term, or None."""
        if isinstance(t, str):
            if t.startswith("#b"):
                return len(t) - 2
            if t.startswith("#x"):
                return 4 * (len(t) - 2)
            return 1 if t in ("true", "false") else None
        sym = self._call(t)
        if sym is not None:
            if sym in self.defs:
                return self._sort_width(self.defs[sym])
            return self.decl_width.get(sym)
        head = t[0] if t else None
        if isinstance(head, list) and head[:2] == ["_", "extract"]:
            return int(head[2]) - int(head[3]) + 1
        if head == "concat":
            ws = [self.term_width(x) for x in t[1:]]
            return None if None in ws else sum(ws)
        if head in ("=", "not", "and", "or", "distinct"):
            return 1
        if head == "ite" and len(t) == 4:
            return self.term_width(t[2])
        return None

    def width_of(self, idx):
        """Bits an assert compares: the widest operand of its equalities, else 1."""
        body = parse_first(self.assert_line[idx])[4]
        if not (isinstance(body, list) and len(body) == 3 and body[0] == "or"):
            return 1
        cond = self._resolve(body[1])
        eqs = cond[1:] if isinstance(cond, list) and cond and cond[0] == "and" else [cond]
        best = 1
        for e in (self._resolve(x) for x in eqs):
            if isinstance(e, list) and len(e) == 3 and e[0] == "=":
                best = max(best, self.term_width(e[1]) or 1)
        return best

    def clock_nets(self):
        """{term: [wire names]} of the distinct clock nets, with aliases resolved to the term they read. A name
        that does not resolve counts as a net of its own, so this can over-count (and refuse) but never merges
        two nets."""
        nets = {}
        for name in self.clock_names:
            line = self.wires.get(name)
            key = f"unresolved {name}"
            if line is not None:
                t = parse_first(line)[4]
                for _ in range(1000):
                    t0 = t
                    t = self._resolve(t)
                    if _is_bool_view(t):
                        t = t[1]
                    if t == t0:
                        break
                key = repr(t)
            nets.setdefault(key, []).append(name)
        return nets
