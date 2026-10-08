# /// script
# requires-python = ">=3.11"
# ///
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import threading
import time
from bisect import insort
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
JPEG = REPO / "internal_assertions" / "jpeg"
RUN = JPEG / "run"
IA = JPEG / "internal_asserts"
EXTRA_SBY = JPEG / "custom_miter_with_extra_asserts_ric3.sby"
PLAIN_SBY = JPEG / "custom_miter_ric3.sby"
ASSERTS_VH = IA / "asserts_yosys.vh"
GOLD = RUN / "gold_out.il"
GATE = RUN / "gate_out.il"

N_OUTPUTS = 5  # miter.v:58..62
N_PAIRS = 182  # default; main() overrides it from the actual asserts_yosys.vh
VH_FIRST_LINE = 2  # asserts_yosys.vh line 2 is pair 0

MARKER_FILES = [
    "PASS",
    "FAIL",
    "UNKNOWN",
    "ERROR",
    "TIMEOUT",
    "CANCELLED",
    "HARDTIMEOUT",
]
PROC_RE = re.compile(
    r"^Elapsed process time \[H:MM:SS \(secs\)\]: \S+ \((\d+)\)$", re.MULTILINE
)
CLOCK_RE = re.compile(
    r"^Elapsed clock time \[H:MM:SS \(secs\)\]: \S+ \((\d+)\)$", re.MULTILINE
)
ASSERT_LINE_RE = re.compile(r"assert\s*\((.*)\)\s*;\s*$")
BAD_RE = re.compile(r"^(\d+)\s+bad\s+(\d+)(?:\s+(\S+))?(?:\s*;\s*(.*?))?\s*$")
NID_RE = re.compile(r"^\s*(\d+)\s")
SRC_RE = re.compile(r"(\S+?):(\d+)\.")


def read_marker(task_dir: Path) -> dict:
    for marker in MARKER_FILES:
        p = task_dir / marker
        if p.exists():
            txt = p.read_text(encoding="utf-8-sig")
            pm, cm = PROC_RE.search(txt), CLOCK_RE.search(txt)
            return {
                "result": marker,
                "process_secs": int(pm.group(1)) if pm else None,
                "clock_secs": int(cm.group(1)) if cm else None,
            }
    return {"result": "NO_MARKER", "process_secs": None, "clock_secs": None}


def sby_sections(text: str) -> dict[str, str]:
    out: dict[str, list[str]] = {}
    cur: str | None = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            cur = s[1:-1]
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v).strip("\n") for k, v in out.items()}


def resolve_files(files_body: str, base: Path) -> str:
    def _abs(p: str) -> str:
        return os.path.normpath(os.path.join(str(base), p))

    out = []
    for raw in files_body.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) == 1:
            out.append(f"{Path(parts[0]).name} {_abs(parts[0])}")
        else:
            out.append(f"{parts[0]} {_abs(parts[1])}")
    return "\n".join(out)


def parse_assert_exprs(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        m = ASSERT_LINE_RE.search(line.strip())
        if m:
            out.append(m.group(1).strip())
    return out


def fmt_ratio(x: float | None) -> str:
    return "-" if x is None else f"{x:.2f}x"


def ratio_fn(plain: dict | None):
    base = plain["wall_secs"] if plain and plain["result"] in ("PASS", "FAIL") else None
    return lambda w: fmt_ratio(w / base if (w and base) else None)


def render_table(rows: list[list[str]]) -> str:
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    out = []
    for ri, r in enumerate(rows):
        out.append("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip())
        if ri == 0:
            out.append("  ".join("-" * widths[i] for i in range(len(r))))
    return "\n".join(out)


def build_base_btor(sby_bin: str, workdir: Path, engine: str, cap_secs: int) -> Path:
    dst = workdir / "base.btor"
    if dst.exists():
        return dst

    sec = sby_sections(EXTRA_SBY.read_text())
    model_sby = workdir / "model.sby"
    model_sby.write_text(
        f"[options]\nmode prove\ntimeout {min(cap_secs, 900)}\n\n"
        f"[engines]\n{engine}\n\n"
        f"[script]\n{sec['script']}\n\n"
        f"[files]\n{resolve_files(sec['files'], RUN)}\n"
    )
    model_wd = workdir / "model"
    if model_wd.exists():
        shutil.rmtree(model_wd)

    btor = model_wd / "model" / "design_btor.btor"
    log = model_wd / "logfile.txt"
    print(f"[base] building BTOR via sby ({sby_bin}) ... (~50s: base -> prep -> btor)")
    proc = subprocess.Popen(
        [sby_bin, "-f", "-d", str(model_wd), str(model_sby)],
        cwd=RUN,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    t0 = time.monotonic()
    last_size, stable, log_pos = -1, 0, 0
    try:
        while True:
            if log.exists():
                with log.open() as fh:
                    fh.seek(log_pos)
                    for ln in fh:
                        if re.search(r"(base|prep|btor): (starting|finished)", ln):
                            print(f"[base]   {ln.strip().split('] ', 1)[-1]}")
                    log_pos = fh.tell()
            if proc.poll() is not None and not btor.exists():
                tail = (
                    log.read_text()[-2000:]
                    if log.exists()
                    else "".join(proc.stdout or [])[-2000:]
                )  # type: ignore[arg-type]
                raise SystemExit(
                    f"[base] sby exited (rc={proc.returncode}) before writing the BTOR.\n"
                    f"       check {log}\n\n{tail}"
                )
            if btor.exists():
                sz = btor.stat().st_size
                stable = stable + 1 if sz == last_size and sz > 0 else 0
                last_size = sz
                if stable >= 2:
                    break
            if time.monotonic() - t0 > cap_secs:
                raise SystemExit(
                    f"[base] BTOR not ready after {cap_secs}s; see {model_wd}"
                )
            time.sleep(1.0)
    finally:
        _kill_group(proc)

    shutil.copy2(btor, dst)
    print(
        f"[base] {dst}  ({dst.stat().st_size // 1024} KiB, "
        f"{time.monotonic() - t0:.0f}s)"
    )
    return dst


def _kill_group(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        proc.wait(timeout=10)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass


class Btor:
    def __init__(self, path: Path):
        self.lines = path.read_text().splitlines()
        self.non_bad: list[str] = []
        self.max_id = 0
        outs: list[tuple[int, int]] = []  # (miter.v line, operand)
        pairs: dict[int, int] = {}  # pair index -> operand
        for line in self.lines:
            m = NID_RE.match(line)
            if m:
                self.max_id = max(self.max_id, int(m.group(1)))
            b = BAD_RE.match(line)
            if not b:
                self.non_bad.append(line)
                continue
            operand, comment = int(b.group(2)), (b.group(4) or "")
            sm = SRC_RE.search(comment)
            if not sm:
                raise SystemExit(f"[btor] bad line without a source comment:\n  {line}")
            fname, lno = sm.group(1), int(sm.group(2))
            if fname.endswith("miter.v"):
                outs.append((lno, operand))
            elif fname.endswith("internal_helper_asserts.vh"):
                pairs[lno - VH_FIRST_LINE] = operand
            else:
                raise SystemExit(
                    f"[btor] unexpected bad-line source {fname}:\n  {line}"
                )

        outs.sort()
        self.out_ops = [op for _, op in outs]
        self.pair_ops = pairs
        if len(self.out_ops) != N_OUTPUTS:
            raise SystemExit(
                f"[btor] expected {N_OUTPUTS} output bads, got {len(self.out_ops)}"
            )
        if sorted(pairs) != list(range(N_PAIRS)):
            raise SystemExit(
                f"[btor] expected internal pairs 0..{N_PAIRS - 1}; got "
                f"{len(pairs)} entries spanning "
                f"{min(pairs, default='-')}..{max(pairs, default='-')}"
            )

    def variant(self, assume_pairs: list[int], target: tuple[str, int] | str) -> str:
        out = list(self.non_bad)
        nid = self.max_id
        for j in assume_pairs:
            out.append(f"{nid + 1} not 1 {self.pair_ops[j]}")
            out.append(f"{nid + 2} constraint {nid + 1}")
            nid += 2
        if isinstance(target, tuple):  # ("pair", i)
            i = target[1]
            out.append(f"{nid + 1} bad {self.pair_ops[i]} _witness_.pair_{i}")
        else:  # "outputs"
            for k, op in enumerate(self.out_ops):
                out.append(f"{nid + 1 + k} bad {op} _witness_.out_{k}")
        return "\n".join(out) + "\n"

    # -- cutting -----------------------------------------------------------
    # `variant` only ever assumes (adds `constraint` on the pair's bad node),
    # which keeps both the gold and the gate logic cone alive.  `variant_cut`
    # instead rewrites the netlist so every use of the gate-side signal of a
    # proven pair points at the gold-side signal; the gate cone behind that
    # frontier register goes dead and rIC3's cone-of-influence pass drops it.
    # Sound on the same basis as the assume: phase 1 has proven the pair equal
    # as an invariant, so the two nodes are interchangeable.

    def prepare_cuts(self) -> None:
        """Index the netlist and locate the (survivor, cut) node pair behind
        every internal-equality property.  Call once before `variant_cut`."""
        self._tok: dict[int, list[str]] = {}
        self._sym: dict[int, str] = {}
        self._sort_of: dict[int, int] = {}
        self._next_of: dict[int, int] = {}
        self._defined: set[int] = set()
        for ln in self.lines:
            s = ln.strip()
            if not s or s[0] == ";":
                continue
            body = s.split(";", 1)[0].split()
            if not body or not body[0].isdigit():
                continue
            nid, op = int(body[0]), body[1]
            if (len(body) > 2 and op not in _CONST_OPS
                    and not body[-1].lstrip("-").isdigit()):
                self._sym[nid] = body[-1]
                body = body[:-1]
            self._tok[nid] = body
            self._defined.add(nid)
            if op == "next" and len(body) >= 5:
                self._next_of[int(body[3])] = int(body[4])
            if op != "sort" and len(body) >= 3 and body[2].isdigit():
                self._sort_of[nid] = int(body[2])

        self._side_of: dict[int, str] = {}
        for nid, name in self._sym.items():
            side = self._name_side(name)
            if side is None:
                continue
            self._side_of.setdefault(nid, side)
            if self._tok[nid][1] in _SKIN_OPS:  # witness alias -> tag the real node
                for r in self._node_args(nid):
                    self._side_of.setdefault(r, side)

        self.cut_points: dict[int, tuple[int, int]] = {}
        self.cut_skipped: dict[int, str] = {}
        cmp_ops = ("eq", "neq", "ne")
        for i, p in self.pair_ops.items():
            try:
                # bad = and(<enable>, not(<violation-flag reg>))
                neg = next(x for x in self._node_args(p)
                           if self._tok[x][1] == "not")
                c = self._node_args(neg)[0]
                # the flag reg: `not` wraps the state directly (async2sync
                # model) or an ite over the state (clk2fflogic model)
                if self._tok[c][1] == "state":
                    sa = c
                else:
                    sa = next(x for x in self._node_args(c)
                              if self._tok[x][1] == "state")
                cmp_id = self._next_of[sa]
                # next(flag) is the compare, or and(<held-so-far>, compare)
                if self._tok[cmp_id][1] == "and":
                    cmp_id = next(x for x in self._node_args(cmp_id)
                                  if self._tok[x][1] in cmp_ops)
                if self._tok[cmp_id][1] not in cmp_ops:
                    raise ValueError(f"cmp op {self._tok[cmp_id][1]}")
                x, y = self._node_args(cmp_id)
            except (StopIteration, KeyError, IndexError, ValueError) as e:
                self.cut_skipped[i] = f"shape ({e})"
                continue
            if self._sort_of.get(x) != self._sort_of.get(y):
                self.cut_skipped[i] = "operand sort mismatch"
                continue
            sx, sy = self._classify(x), self._classify(y)
            if {sx, sy} != {"gold", "gate"}:
                self.cut_skipped[i] = f"side {sx}/{sy}"
                continue
            # keep the lower id as survivor: no forward reference is possible,
            # since the lower id is defined before any use of the higher one.
            self.cut_points[i] = (min(x, y), max(x, y))

    @staticmethod
    def _name_side(name: str) -> str | None:
        if re.search(r"(_a$|_a\[)", name) or "dut_a." in name:
            return "gold"
        if re.search(r"(_b$|_b\[)", name) or "dut_b." in name:
            return "gate"
        return None

    def _node_args(self, nid: int) -> list[int]:
        t = self._tok.get(nid)
        if not t:
            return []
        op = t[1]
        if op == "sort" or op in _VALUE_OPS:
            return []
        raw = t[3:]
        cut = _TAIL_CONSTS.get(op)
        if cut:
            raw = raw[:-cut] if len(raw) > cut else []
        out = []
        for tok in raw:
            v = tok[1:] if tok[:1] == "-" else tok
            if v.isdigit() and int(v) in self._defined:
                out.append(int(v))
        return out

    def _classify(self, n: int) -> str | None:
        s = self._side_of.get(n)
        if s:
            return s
        g = self._cone_hits(n, "gold")
        b = self._cone_hits(n, "gate")
        return "gold" if g and not b else "gate" if b and not g else None

    def _cone_hits(self, start: int, side: str, limit: int = 200_000) -> bool:
        stack, seen = [start], set()
        while stack and len(seen) < limit:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            if self._side_of.get(x) == side:
                return True
            stack.extend(self._node_args(x))
            nx = self._next_of.get(x)
            if nx is not None:
                stack.append(nx)
        return False

    def variant_cut(
        self,
        cut_pairs: list[int],
        assume_pairs: list[int],
        target: tuple[str, int] | str,
    ) -> str:
        subst: dict[int, int] = {}
        for j in cut_pairs:
            cp = self.cut_points.get(j)
            if cp is None:
                raise SystemExit(
                    f"[cut] pair {j} has no cut point ({self.cut_skipped.get(j)})"
                )
            surv, dead = cp
            subst[dead] = surv

        def resolve(n: int) -> int:
            seen: set[int] = set()
            while n in subst and n not in seen:
                seen.add(n)
                n = subst[n]
            return n

        rmap = {k: resolve(k) for k in subst}

        def rewrite(line: str) -> str:
            body, sep, comment = line.partition(";")
            t = body.split()
            if len(t) < 4 or not t[0].isdigit() or t[1] in _CONST_OPS:
                return line
            for k in range(3, len(t)):
                tok = t[k]
                neg = tok[:1] == "-"
                v = tok[1:] if neg else tok
                if v.isdigit() and int(v) in rmap:
                    t[k] = ("-" if neg else "") + str(rmap[int(v)])
            return " ".join(t) + (sep + comment if sep else "")

        out = [rewrite(l) for l in self.non_bad]
        nid = self.max_id
        for j in assume_pairs:
            op = rmap.get(self.pair_ops[j], self.pair_ops[j])
            out.append(f"{nid + 1} not 1 {op}")
            out.append(f"{nid + 2} constraint {nid + 1}")
            nid += 2
        if isinstance(target, tuple):  # ("pair", i)
            i = target[1]
            op = rmap.get(self.pair_ops[i], self.pair_ops[i])
            out.append(f"{nid + 1} bad {op} _witness_.pair_{i}")
        else:  # "outputs"
            for k, op in enumerate(self.out_ops):
                out.append(f"{nid + 1 + k} bad {rmap.get(op, op)} _witness_.out_{k}")
        return "\n".join(out) + "\n"


_VALUE_OPS = {"const", "constd", "consth", "one", "ones", "zero"}
_TAIL_CONSTS = {"slice": 2, "sext": 1, "uext": 1, "rol": 1, "ror": 1}
_SKIN_OPS = {"uext", "sext", "slice"}
_CONST_OPS = {"sort", "const", "constd", "consth"}


def parse_edges(
    lines: list[str],
) -> tuple[dict[int, tuple[str, list[int]]], dict[int, int]]:
    defined: set[int] = set()
    rows: list[list[str]] = []
    for ln in lines:
        s = ln.strip()
        if not s or s[0] == ";":
            continue
        t = s.split()
        if not t[0].isdigit():
            continue
        defined.add(int(t[0]))
        rows.append(t)

    def _num(tok: str) -> int | None:
        v = tok[1:] if tok[:1] == "-" else tok  # operands may be negated
        return int(v) if v.isdigit() and int(v) in defined else None

    edges: dict[int, tuple[str, list[int]]] = {}
    state_next: dict[int, int] = {}
    for t in rows:
        nid, op = int(t[0]), t[1]
        if op == "next" and len(t) >= 5:  # <nid> next <sort> <st> <val>
            st, val = _num(t[3]), _num(t[4])
            if st is not None and val is not None:
                state_next[st] = val
        if op == "sort" or op in _VALUE_OPS:
            edges[nid] = (op, [])
            continue
        toks = t[3:]  # skip nid, op, sort
        cut = _TAIL_CONSTS.get(op)
        if cut:
            toks = toks[:-cut] if len(toks) > cut else []
        args = []
        for tok in toks:
            if tok[:1] == ";":
                break
            v = _num(tok)
            if v is not None:
                args.append(v)
        edges[nid] = (op, args)
    return edges, state_next


def reg_depth(edges: dict, state_next: dict) -> dict[int, int]:
    def preds_of(n: int) -> list[int]:
        op, args = edges.get(n, ("?", ()))
        p = list(args)
        if op == "state" and n in state_next:
            p.append(state_next[n])
        return p

    memo: dict[int, int] = {}
    for start in list(edges):
        if start in memo:
            continue
        stack = [(start, False)]
        visiting: set[int] = set()
        while stack:
            n, done = stack.pop()
            if done:
                base = max((memo.get(a, 0) for a in preds_of(n)), default=0)
                memo[n] = base + (1 if edges.get(n, ("?", ()))[0] == "state" else 0)
                visiting.discard(n)
                continue
            if n in memo or n in visiting:
                continue
            visiting.add(n)
            stack.append((n, True))
            for a in preds_of(n):
                if a not in memo and a not in visiting:
                    stack.append((a, False))
    return memo


def compute_order(btor: Btor, cache: Path, base_mtime: float) -> list[int]:
    ids = list(range(N_PAIRS))
    if cache.exists() and cache.stat().st_mtime >= base_mtime:
        cached = json.loads(cache.read_text())
        if len(cached) == N_PAIRS:
            print("[order] reusing cached 'depth' order")
            return cached
    print(f"[order] computing 'depth' order over {btor.max_id} BTOR nodes ...")
    t0 = time.monotonic()
    edges, state_next = parse_edges(btor.lines)
    d = reg_depth(edges, state_next)
    tc = {i: d.get(btor.pair_ops[i], 0) for i in ids}
    out = sorted(ids, key=lambda i: (tc[i], i))
    cache.write_text(json.dumps(out))
    print(
        f"[order] depth: pair {out[0]} first ({tc[out[0]]} reg-depth) .. "
        f"pair {out[-1]} last ({tc[out[-1]]})   [{time.monotonic() - t0:.1f}s]"
    )
    return out


def run_ric3(
    ric3_bin: str,
    eng_args: list[str],
    btor: Path,
    timeout: int | None,
    stream: bool = False,
) -> dict:
    t0 = time.monotonic()
    proc = subprocess.Popen(
        [ric3_bin, "--witness", *eng_args, str(btor)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    timed_out = False

    def _watchdog() -> None:
        nonlocal timed_out
        timed_out = True
        _kill_group(proc)

    timer = threading.Timer(timeout, _watchdog) if timeout is not None else None
    if timer is not None:
        timer.start()
    captured: deque[str] = deque(maxlen=4000)
    try:
        for ln in proc.stdout:  # type: ignore[union-attr]
            captured.append(ln)
            if stream:
                print(f"    [ric3] {ln.rstrip()}", flush=True)
        proc.wait()
    finally:
        if timer is not None:
            timer.cancel()

    out = "".join(captured)
    rc = None if timed_out else proc.returncode
    wall = round(time.monotonic() - t0, 1)
    tail = next((l.strip() for l in reversed(out.splitlines()) if l.strip()), "")

    if timed_out:
        result = "TIMEOUT"
    elif rc == 20 or (rc not in (10,) and re.search(r"(?<![A-Za-z])UNSAT\b", out)):
        result = "PASS"
    elif rc == 10 or re.search(r"(?<![A-Za-z])SAT\b", out):
        result = "FAIL"
    else:
        result = "UNKNOWN"
    return {"result": result, "wall_secs": wall, "returncode": rc, "tail": tail}


def run_plain(sby_bin: str, workdir: Path, engine: str, timeout: int) -> dict:
    sec = sby_sections(PLAIN_SBY.read_text())
    plain_sby = workdir / "plain.sby"
    plain_sby.write_text(
        f"[options]\nmode prove\ntimeout {timeout}\n\n"
        f"[engines]\n{engine}\n\n"
        f"[script]\n{sec['script']}\n\n"
        f"[files]\n{resolve_files(sec['files'], RUN)}\n"
    )
    wd = workdir / "plain"
    if wd.exists():
        shutil.rmtree(wd)
    print("[plain] running sby ...")
    t0 = time.monotonic()
    subprocess.run(
        [sby_bin, "-f", "-d", str(wd), str(plain_sby)],
        cwd=RUN,
        capture_output=True,
        text=True,
    )
    r = {
        "phase": "plain",
        "wall_secs": round(time.monotonic() - t0, 1),
        **read_marker(wd),
    }
    print(f"[plain] {r['result']}  wall={r['wall_secs']}s")
    return r


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--engine", default="btor rIC3 -e ic3 --ic3-inn")
    ap.add_argument("--pair-timeout", type=int, default=180)
    ap.add_argument("--plain-timeout", type=int, default=3600)
    ap.add_argument("--pool", type=int, default=1)
    ap.add_argument("--retry-nonpass", action="store_true")
    ap.add_argument("--experiment-assume-all", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument(
        "--cut",
        action="store_true",
        help="phase 2 / experiment: cut every proven pair (alias the gate-side "
        "signal onto the gold-side one) instead of only assuming it; falls back "
        "to assume for any pair whose cut point can't be located",
    )
    args = ap.parse_args()

    for tool in ("sby", "rIC3"):
        if not shutil.which(tool):
            raise SystemExit(f"{tool} not on PATH (need the oss-cad-suite env)")
    sby_bin, ric3_bin = shutil.which("sby"), shutil.which("rIC3")

    for p in (EXTRA_SBY, PLAIN_SBY, ASSERTS_VH, GOLD, GATE):
        if not p.exists():
            raise SystemExit(
                f"missing {p}\n"
                "run `make custom-miter-extra-asserts` in internal_assertions/jpeg first"
            )

    tok = shlex.split(args.engine)
    if len(tok) < 2 or tok[0] != "btor" or tok[1].lower() != "ric3":
        raise SystemExit(f"--engine must start with 'btor rIC3', got {args.engine!r}")
    eng_args = tok[2:]

    label = "jpeg__" + re.sub(r"[^A-Za-z0-9]+", "-", args.engine).strip("-")
    workdir = HERE / "work" / label
    out_dir = HERE / "results" / label
    workdir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    pairs_json = out_dir / "pairs.json"

    global N_PAIRS
    exprs = parse_assert_exprs(ASSERTS_VH.read_text())
    if not exprs:
        raise SystemExit(f"no asserts parsed from {ASSERTS_VH}")
    N_PAIRS = len(exprs)

    runtag = "cut" if args.cut else "assume"
    print(f"label       {label}")
    print(f"engine      {args.engine}   (rIC3 args: {' '.join(eng_args) or '(none)'})")
    print(
        f"timeouts    pair={args.pair_timeout}s  plain={args.plain_timeout}s   "
        f"pool={args.pool}"
    )
    print(f"phase 2     {'cut proven pairs (alias gate->gold)' if args.cut else 'assume proven pairs'}")
    print(f"workdir     {workdir}\n")

    base_cache = workdir / "base.btor"
    btor_inputs = [
        GOLD,
        GATE,
        JPEG / "miter.v",
        ASSERTS_VH,
        EXTRA_SBY,
        IA / "decls_yosys.vh",
        IA / "ports_a_yosys.vh",
        IA / "ports_b_yosys.vh",
        IA / "expose_yosys.ys",
    ]
    if base_cache.exists():
        newest = max((p.stat().st_mtime for p in btor_inputs if p.exists()), default=0)
        if newest > base_cache.stat().st_mtime:
            print("[base] a jpeg input changed since the cached base.btor; rebuilding")
            base_cache.unlink()
        else:
            print(f"[base] reusing cached {base_cache}")
    base_path = build_base_btor(sby_bin, workdir, args.engine, cap_secs=1200)
    btor = Btor(base_path)
    print(
        f"[btor] {btor.max_id} nodes, {len(btor.out_ops)} output + "
        f"{len(btor.pair_ops)} internal properties\n"
    )

    if args.cut:
        t0 = time.monotonic()
        btor.prepare_cuts()
        n_ok = len(btor.cut_points)
        print(
            f"[cut] located cut points for {n_ok}/{N_PAIRS} pairs "
            f"[{time.monotonic() - t0:.1f}s]"
        )
        for i in sorted(btor.cut_skipped):
            print(f"[cut]   pair {i:3d}  no cut point ({btor.cut_skipped[i]}) "
                  f"-> will be assumed")
        print()

    def prove_outputs(
        assume_ids: list[int], phase: str, tag: str, extra: str = ""
    ) -> dict:
        """Discharge `assume_ids` (cut where possible when --cut, else assume) and
        prove the 5 outputs; no timeout, streamed. Shared by phase 2 and the
        experiment."""
        ids = sorted(assume_ids)
        if args.cut:
            cut_ids = [j for j in ids if j in btor.cut_points]
            keep = [j for j in ids if j not in btor.cut_points]
            text = btor.variant_cut(cut_ids, keep, "outputs")
            how = f"cut {len(cut_ids)} + assume {len(keep)}"
        else:
            text = btor.variant(ids, "outputs")
            how = f"assume {len(ids)}"
        pb = workdir / f"{phase}.btor"
        pb.write_text(text)
        print(
            f"[{tag}] {how} pairs{extra}, prove {N_OUTPUTS} outputs "
            f"(no timeout, streaming rIC3 output) ..."
        )
        r = {
            "phase": phase,
            "assumed": len(ids),
            "cut": len(cut_ids) if args.cut else 0,
            **run_ric3(ric3_bin, eng_args, pb, None, stream=True),
        }
        pb.unlink(missing_ok=True)
        print(f"[{tag}] {r['result']}  wall={r['wall_secs']}s")
        return r

    if args.experiment_assume_all:
        exp = prove_outputs(
            list(range(N_PAIRS)),
            f"experiment-{runtag}-all",
            "experiment",
            extra=" (all, unproven)",
        )

        plain = run_plain(sby_bin, workdir, args.engine, args.plain_timeout)

        r = ratio_fn(plain)
        rows = [
            ["phase", "result", "wall (s)", "x vs plain"],
            [
                "plain (outputs only)",
                plain["result"],
                str(plain["wall_secs"]),
                r(plain["wall_secs"]),
            ],
            [
                f"{'cut' if args.cut else 'assume'} all {N_PAIRS} + prove outputs",
                exp["result"],
                str(exp["wall_secs"]),
                r(exp["wall_secs"]),
            ],
        ]
        print("\n" + render_table(rows))
        print(
            f"\nNote: all {N_PAIRS} pairs are "
            f"{'cut' if args.cut else 'assumed'} without proof (phase 1 skipped), so a "
            "false equality cannot be ruled out. This verdict is an upper bound on the "
            f"{'cut' if args.cut else 'assume'} approach, not a sound result."
        )

        meta = {
            "label": label,
            "engine": args.engine,
            "experiment": f"{runtag}-all-pairs-no-phase1",
            "sound": False,
            "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "internal_eq_pairs": N_PAIRS,
            "experiment_result": exp,
            "plain": plain,
        }
        exp_json = out_dir / f"experiment_{runtag}_all.json"
        exp_json.write_text(json.dumps(meta, indent=2))
        print(f"\nwrote {exp_json}")
        return

    recorded: dict[int, dict] = {}
    if args.resume and pairs_json.exists():
        stale = 0
        for e in json.loads(pairs_json.read_text()):
            i = e["pair"]
            if i >= N_PAIRS or e.get("expr") != exprs[i]:
                stale += 1
                continue
            recorded[i] = e
        print(f"[resume] {len(recorded)} pairs already recorded"
              + (f"  ({stale} dropped: assert set changed)" if stale else ""))

    def eff(e: dict) -> str:
        """effective result: retry verdict if the pair was retried, else phase 1."""
        return e.get("retry", e)["result"]

    passed: list[int] = sorted(i for i, e in recorded.items() if eff(e) == "PASS")
    lock = threading.Lock()
    total = N_PAIRS
    order = compute_order(btor, workdir / "order_depth.json", base_path.stat().st_mtime)
    todo = [i for i in order if i not in recorded]

    def flush() -> None:
        pairs_json.write_text(
            json.dumps([recorded[i] for i in sorted(recorded)], indent=2)
        )

    def run_one(i: int, assume_ids: list[int], timeout: int) -> dict:
        vb = workdir / f"pair_{i}.btor"
        vb.write_text(btor.variant(sorted(assume_ids), ("pair", i)))
        try:
            return run_ric3(ric3_bin, eng_args, vb, timeout)
        finally:
            vb.unlink(missing_ok=True)

    def tally() -> tuple[int, int, int, int]:
        p = sum(1 for e in recorded.values() if eff(e) == "PASS")
        f = sum(1 for e in recorded.values() if eff(e) == "FAIL")
        t = sum(1 for e in recorded.values() if eff(e) == "TIMEOUT")
        return p, f, t, len(recorded) - p - f - t

    def work(i: int) -> None:
        with lock:
            assume = list(passed)
        r = run_one(i, assume, args.pair_timeout)
        with lock:
            recorded[i] = {"pair": i, "expr": exprs[i], "assumed": len(assume), **r}
            if r["result"] == "PASS":
                insort(passed, i)
            flush()
            done = len(recorded)
        mark = "" if r["result"] == "PASS" else f"   <<< {r['result']}"
        print(
            f"  [{done:3d}/{total}] pair {i:3d}  {r['result']:8s} "
            f"{r['wall_secs']:6.1f}s  (assumed {len(assume)}){mark}"
        )

    if todo:
        print(
            f"[phase 1] validating {len(todo)} pairs ({len(recorded)} already done, "
            f"pool={args.pool}) ..."
        )
        if args.pool <= 1:
            for i in todo:
                work(i)
        else:
            with ThreadPoolExecutor(max_workers=args.pool) as ex:
                list(ex.map(work, todo))
    flush()

    n_pass, n_fail, n_to, n_unk = tally()
    print(
        f"\n[phase 1] {n_pass} PASS / {n_fail} FAIL / {n_to} TIMEOUT / {n_unk} UNKNOWN "
        f"of {len(recorded)}"
    )

    n_recovered = 0
    if args.retry_nonpass:
        frozen = list(passed)
        want = {"TIMEOUT", "UNKNOWN", "FAIL"}
        retry_ids = [
            i
            for i in sorted(recorded)
            if eff(recorded[i]) in want and "retry" not in recorded[i]
        ]
        rt = max(args.pair_timeout, 300)

        def work_retry(i: int) -> None:
            assume = [j for j in frozen if j != i]
            r = run_one(i, assume, rt)
            with lock:
                old = recorded[i]["result"]
                recorded[i] = {
                    **recorded[i],
                    "retry": {"from": old, "assumed": len(assume), **r},
                }
                if r["result"] == "PASS" and i not in passed:
                    insort(passed, i)
                flush()
            note = f"  {old} -> {r['result']}"
            if old == "FAIL" and r["result"] == "PASS":
                note += "   <<< FAIL->PASS, REVIEW"
            print(
                f"  [retry] pair {i:3d}  {r['result']:8s} {r['wall_secs']:7.1f}s{note}"
            )

        if retry_ids:
            print(
                f"\n[retry] re-running {len(retry_ids)} non-pass pairs against the "
                f"frozen {len(frozen)}-pair passed set (timeout {rt}s, pool={args.pool}) ..."
            )
            if args.pool <= 1:
                for i in retry_ids:
                    work_retry(i)
            else:
                with ThreadPoolExecutor(max_workers=args.pool) as ex:
                    list(ex.map(work_retry, retry_ids))
            flush()
            n_recovered = sum(1 for i in retry_ids if eff(recorded[i]) == "PASS")
            n_pass, n_fail, n_to, n_unk = tally()
            print(
                f"[retry] recovered {n_recovered}/{len(retry_ids)} pairs  "
                f"-> {n_pass} PASS total"
            )

    validate_wall = round(
        sum(e["wall_secs"] for e in recorded.values())
        + sum(e["retry"]["wall_secs"] for e in recorded.values() if "retry" in e),
        1,
    )
    phase2 = prove_outputs(passed, f"{runtag}+prove", "phase 2")
    plain = run_plain(sby_bin, workdir, args.engine, args.plain_timeout)

    ratio = ratio_fn(plain)
    vlabel = f"validate {len(recorded)} pairs"
    if n_recovered:
        vlabel += " + retry"
    rows = [
        ["phase", "result", "wall (s)", "x vs plain"],
        [
            "plain (outputs only)",
            plain["result"],
            str(plain["wall_secs"]),
            ratio(plain["wall_secs"]),
        ],
    ]
    rows.append(
        [
            vlabel,
            f"{n_pass}/{len(recorded)} PASS",
            str(validate_wall),
            ratio(validate_wall),
        ]
    )
    p2_verb = "cut" if args.cut else "assume"
    if phase2:
        p2_n = (
            f"cut {phase2.get('cut', 0)}/{phase2['assumed']}"
            if args.cut
            else f"assume {phase2['assumed']}"
        )
        rows.append(
            [
                f"{p2_n} + prove outputs",
                phase2["result"],
                str(phase2["wall_secs"]),
                ratio(phase2["wall_secs"]),
            ]
        )
    table = render_table(rows)

    extra = []
    if phase2:
        first = validate_wall + (phase2["wall_secs"] or 0)
        extra.append(
            f"first sound answer (validate + {p2_verb}+prove): {first:.1f}s  "
            f"({ratio(first)})"
        )
        extra.append(
            f"{p2_verb} alone (validation amortized): {phase2['wall_secs']}s  "
            f"({ratio(phase2['wall_secs'])})"
        )
    extra.append(
        f"pairs: {n_pass} PASS / {n_fail} FAIL / {n_to} TIMEOUT / {n_unk} UNKNOWN"
        + (f"   ({n_recovered} recovered by retry)" if n_recovered else "")
    )
    for i in sorted(recorded):
        e = recorded[i]
        if eff(e) == "PASS":
            continue
        via = f"  (retry {e['retry']['from']}->{eff(e)})" if "retry" in e else ""
        extra.append(f"  pair {i:3d} {eff(e):8s}  {e['expr']}{via}")

    print("\n" + table)
    for ln in extra:
        print(ln)

    meta = {
        "label": label,
        "engine": args.engine,
        "pair_timeout": args.pair_timeout,
        "retry_nonpass": args.retry_nonpass,
        "phase2_mode": "cut" if args.cut else "assume",
        "phase2_cut_pairs": (phase2 or {}).get("cut", 0),
        "phase2_uncuttable": sorted(btor.cut_skipped) if args.cut else [],
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "internal_eq_pairs": N_PAIRS,
        "counts": {"PASS": n_pass, "FAIL": n_fail, "TIMEOUT": n_to, "UNKNOWN": n_unk},
        "recovered_by_retry": n_recovered,
        "validate_wall_secs": validate_wall,
        "passed_pairs": passed,
        "plain": plain,
        "phase2": phase2,
        "pairs": [recorded[i] for i in sorted(recorded)],
    }
    results_json = out_dir / f"results_{runtag}.json" if args.cut else out_dir / "results.json"
    summary_md = out_dir / f"summary_{runtag}.md" if args.cut else out_dir / "summary.md"
    p2_desc = (
        "Phase 2 cuts every passed pair — the gate-side signal is aliased onto "
        "the proven-equal gold-side signal, so the gate cone behind that frontier "
        "goes dead"
        + (f" (a further {len(btor.cut_skipped)} pair(s) had no locatable cut "
           "point and were assumed instead)" if btor.cut_skipped else "")
        if args.cut
        else "Phase 2 assumes every passed pair"
    )
    results_json.write_text(json.dumps(meta, indent=2))
    summary_md.write_text(
        f"# jpeg per-pair validate -> {runtag}: `{label}`\n\n"
        f"- engine: `{args.engine}`\n"
        f"- per-pair timeout {args.pair_timeout}s"
        + (", retry-nonpass on" if args.retry_nonpass else "")
        + "\n"
        f"- internal equivalence pairs: **{N_PAIRS}**\n"
        f"- generated: {meta['generated_utc']}\n\n"
        "```\n" + table + "\n" + "\n".join(extra) + "\n```\n\n"
        "Phase 1 proves each internal register-pair equality on its own, assuming the "
        "pairs already passed (sound: only discharged lemmas are assumed). "
        + (
            "The retry round re-runs the non-pass pairs once against the frozen full "
            "passed set (still a single sound round). "
            if args.retry_nonpass
            else ""
        )
        + p2_desc + ", and proves the 5 primary-output "
        "equalities. `plain` is the untouched output-only miter.\n"
    )
    print(f"\nwrote {summary_md} and {results_json}")


if __name__ == "__main__":
    main()
