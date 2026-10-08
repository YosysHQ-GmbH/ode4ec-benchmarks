#!/usr/bin/env python3
"""Build the single-clock SMT2 model seq_prove.py works on, from a benchmark run directory.

usage: build_model.py RUN_DIR OUT_DIR [--sby miter_extra_asserts.sby] [--task T] [--miter miter.v]
                      [--regen [--match-gate-wires] [--const-candidates] [--fsm-candidates]
                               [--range-candidates] [--guarded-candidates]
                               [--regen-name KEY=FILE ...]]
                      [--replace gate.il=/path/to/mutant.il ...] [--allow-latches]

RUN_DIR holds an sby file (--sby, relative to RUN_DIR) whose [script] builds the miter and whose [files]
lists the inputs. The model is built by that script with these changes:
  - clk2fflogic is removed, so one SMT step is one clock cycle. This is only sound for a single posedge
    clock: the guards refuse negedge, derived and multiple clocks, and latches.
  - Clocked blocks of the miter that contain only asserts become `always @*`. A sampled assert would turn
    `--k K` into K-1 induction.
  - `prep`, `dffunmap` and `write_smt2 -wires model.smt2` are appended.
Writes OUT_DIR/model.smt2, build.ys, build.log and build.json.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

# (message, selection that must be empty). Checked before async2sync, which turns latches into $ff, and
# after prep, whose proc turns processes into cells.
GUARDS = [
    ("negedge flip-flops (need clk2fflogic)",
     "t:$*dff* r:CLK_POLARITY=1'b0 %i t:$*dff* r:CLK_POLARITY=0 %i %u t:$_*_N* %u"),
    ("tristate buffers", "t:$tribuf t:$_TBUF_ %u"),
]
LATCH_GUARD = ("latches (async2sync would model them as sampled flip-flops, --allow-latches accepts that)",
               "t:$*latch* t:$_DLATCH* %u t:$_SR_* %u")
# The model steps every flip-flop with one global clock, so all of them must be clocked by the same 1-bit
# top-level input. The polarity guard only looks at the cell, not at what drives its clock pin (an inverter,
# gating logic, another input or a constant). Clocked memory ports must use the same input. Memory port clock
# polarity is not checked. Run after prep, when flip-flops are cells and each net has one name.
CLOCK_GUARD_MSG = ("flip-flops not all clocked by one 1-bit top-level input (derived, gated, constant or several "
                   "clocks need clk2fflogic)")
CLOCK_GUARD = [
    "select -set __gff t:$*dff* t:$_DFF* %u t:$_SDFF* %u t:$_ALDFF* %u",
    "select -set __gclk @__gff t:$mem* %u %x1:+[CLK,C,RD_CLK,WR_CLK] w:* %i",
    "select -assert-max 1 @__gclk",
    "select -assert-none @__gclk i:* %d @__gclk s:2:2147483647 %i %u",
    "select -assert-none @__gff @__gclk %x1:+[CLK,C] %d",
]


REGEN_FILES = {"gold": "gold.il", "gate": "gate.il", "expose": "expose.ys", "decls": "decls.vh",
               "ports_a": "ports_a.vh",
               "ports_b": "ports_b.vh", "asserts": "asserts.vh"}


def sby_sections(text):
    sec, out = None, {}
    for line in text.split("\n"):
        m = re.match(r"^\[(\w+)\]\s*$", line)
        if m:
            sec = m.group(1)
            out[sec] = []
        elif sec:
            out[sec].append(line)
    return out


def sby_tasks(lines, where):
    """{task: tags} from a [tasks] section (`task1 task2: tag1 tag2` or `task tag1 tag2`)."""
    tasks = {}
    for ln in lines:
        if ln.startswith("#") or not ln.strip():
            continue
        parts = ln.split(":")
        if len(parts) > 2:
            sys.exit(f"{where}: syntax error in [tasks] line {ln!r}")
        lhs, rhs = (parts[0].split()[:1], parts[0].split()[1:]) if len(parts) == 1 else \
            (parts[0].split(), parts[1].split())
        for n in lhs + rhs:
            if any(c in "(?*.[]|)" for c in n):
                sys.exit(f"{where}: task name patterns are not supported: {n!r}")
        for t in lhs:
            tasks.setdefault(t, set()).update(g for g in rhs if g != "default")
    return tasks


def select_task(lines, tasks, task, where):
    """Apply sby task conditionals: `t: line`, `~t: line`, and `t:` blocks ending at `--`."""
    names = set(tasks) | {g for gs in tasks.values() for g in gs}
    active = {task} | tasks.get(task, set()) if task is not None else set()
    out, block = [], None  # None outside a block, else whether its lines are kept
    for line in lines:
        if block is not None and line.strip() == "--":
            block = None
            continue
        t = next((n for n in names if line.startswith((n + ":", "~" + n + ":"))), None)
        if t is None:
            tok = line.split()
            if names and tok and tok[0][0] == line[0] and tok[0].endswith(":"):
                sys.exit(f"{where}: invalid task specifier {tok[0]!r}")
            if block is not False:
                out.append(line)
            continue
        if task is None:
            sys.exit(f"{where}: script has task conditionals, choose one of {sorted(tasks)} with --task")
        neg = line.startswith("~")
        rest = line[len(t) + 1 + neg:].lstrip()
        match = (t in active) != neg
        if rest == "":
            block = match
        elif match and block is not False:
            out.append(rest)
    return out


# optional label, optional `else $error("...")`
_ASSERT_LINE = re.compile(r"^\s*(\w+\s*:\s*)?assert\s*\(.*\)\s*"
                          r"(else\s+\$(error|warning|info|fatal)\s*\(\s*(\"[^\"]*\")?\s*\)\s*)?;\s*(//.*)?$")
_ALLOWED = re.compile(r"^\s*(//.*|`(ifdef|ifndef|else|elsif|endif)\b.*|)$")
_INCLUDE = re.compile(r'^\s*`include\s+"([^"]+)"\s*$')


def _check_assert_lines(lines, where, incdir):
    for ln in lines:
        m = _INCLUDE.match(ln)
        if m:
            inc = incdir / m.group(1)
            if not inc.exists():
                sys.exit(f"{where}: included file {inc} not found")
            _check_assert_lines(inc.read_text().split("\n"), inc.name, incdir)
        elif not (_ASSERT_LINE.match(ln) or _ALLOWED.match(ln)):
            sys.exit(f"{where}: clocked block contains more than asserts, not converted: {ln.strip()!r}")


# a signal, struct member or indexed signal
_OPERAND = r"[A-Za-z_][\w$]*(?:\s*(?:\.[A-Za-z_][\w$]*|\[[^\[\]]*\]))*"
_EQ_ASSERT = re.compile(rf"^\s*(?:\w+\s*:\s*)?assert\s*\(\s*({_OPERAND})\s*==\s*({_OPERAND})\s*\)")


def bit_candidate_files(props):
    """(declarations, candidates): per-bit candidates `ihv_outN_a[i] == ihv_outN_b[i]` for each equality
    property A == B, over flat copies of A and B (B fitted to A's width)."""
    # a generate loop, because yosys-slang limits procedural loops to 4000 iterations
    decls, cands = [], []
    for n, (a, b) in enumerate(props):
        decls += [f"wire [$bits({a})-1:0] ihv_out{n}_a = {a};", f"wire [$bits({a})-1:0] ihv_out{n}_b = {b};"]
        loop = (f"generate for (ihv_g{n} = 0; ihv_g{n} < $bits(ihv_out{n}_a); ihv_g{n} = ihv_g{n} + 1) "
                f"begin : ihv_bits{n} always @* assert(ihv_out{n}_a[ihv_g{n}] == ihv_out{n}_b[ihv_g{n}]); "
                "end endgenerate")
        cands += [f"genvar ihv_g{n};", loop]
    return "\n".join(decls) + "\n", "\n".join(cands) + "\n"


def comb_miter(text, incdir, bits_stem=None):
    """(text, blocks, props): turn `always[_ff] @(posedge X) begin <asserts only> end` into `always @*`.
    With bits_stem, also include the bit candidates of the equality asserts before the first block."""
    lines, out, n, i, props = text.split("\n"), [], 0, 0, []
    head = re.compile(r"^(\s*)always(_ff)?\s*@\s*\(\s*posedge\s+[A-Za-z_][\w$]*\s*\)\s*begin\s*(//.*)?$")
    while i < len(lines):
        m = head.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        depth, j = 1, i + 1
        while j < len(lines) and depth:
            code = lines[j].split("//")[0]
            depth += len(re.findall(r"\bbegin\b", code)) - len(re.findall(r"\bend\b", code))
            j += 1
        body = lines[i + 1:j - 1]
        if depth or lines[j - 1].split("//")[0].strip() != "end":
            sys.exit(f"miter line {i + 1}: could not find the end of the clocked block")
        if not any(re.search(r"\bassert\b|`include\b", ln.split("//")[0]) for ln in body):
            out.extend(lines[i:j])        # clocked logic without asserts
            i = j
            continue
        _check_assert_lines(body, f"miter line {i + 1}", incdir)
        first = bits_stem and n == 0      # declared once, before the first block
        if bits_stem:
            props += [mm.groups() for mm in map(_EQ_ASSERT.match, body) if mm]
        if first:
            out.append(f'{m.group(1)}`include "{bits_stem}_decls.vh"')
            out.append(f'{m.group(1)}`include "{bits_stem}.vh"')
        out.append(f"{m.group(1)}always @* begin")
        out.extend(lines[i + 1:j])
        n += 1
        i = j
    return "\n".join(out), n, props


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--sby", default="miter_extra_asserts.sby")
    ap.add_argument("--task", help="sby task whose conditional script/files lines to use")
    ap.add_argument("--miter", default="miter.v")
    ap.add_argument("--regen", action="store_true", help="regenerate asserts with _common/generate_internal_asserts")
    ap.add_argument("--match-gate-wires", action="store_true")
    ap.add_argument("--const-candidates", action="store_true")
    ap.add_argument("--fsm-candidates", action="store_true",
                    help="--regen: state-encoding candidates for gold registers the gate re-encoded (same-named "
                         "gate bits beyond the gold width, e.g. yosys one-hot FSM recoding)")
    ap.add_argument("--range-candidates", action="store_true",
                    help="--regen: `register != k` for every value k of each small gold register (2..6 bits): "
                         "Houdini keeps the unreachable values, where RTL and netlist may differ (don't-cares)")
    ap.add_argument("--guarded-candidates", action="store_true",
                    help="--regen: `guard -> register bits equal` for multi-bit gold registers, guard = a 1-bit "
                         "register of the same scope or an edge bit of the register itself (both polarities): "
                         "for registers that hold don't-care data while their valid bit is clear")
    ap.add_argument("--output-bit-candidates", action="store_true",
                    help="one candidate per bit of each equality property `A == B` of the miter's assert block, "
                         "in <miter>_bits.vh (pass it to seq_prove --candidates): Houdini can keep the bits that "
                         "are inductive when the whole wide property is not")
    ap.add_argument("--regen-name", action="append", default=[], metavar="KEY=FILE",
                    help="--regen file names (KEY: " + ", ".join(REGEN_FILES) + "), defaults as in the frontier "
                         "runs, e.g. gold=gold_out.il asserts=internal_helper_asserts.vh")
    ap.add_argument("--replace", action="append", default=[], metavar="NAME=PATH",
                    help="use PATH instead of the run's input NAME (e.g. a mutated gate.il)")
    ap.add_argument("--allow-latches", action="store_true")
    return ap.parse_args()


def read_sby(sby, task):
    """The [script] and [files] lines of the task."""
    sec = sby_sections(sby.read_text())
    if "script" not in sec or "files" not in sec:
        sys.exit(f"{sby}: no [script] or [files] section")
    tasks = sby_tasks(sec.get("tasks", []), f"{sby} [tasks]")
    if task is not None and task not in tasks:
        sys.exit(f"--task {task}: not among the sby tasks {sorted(tasks)}")
    return [select_task(sec[s], tasks, task, f"{sby} [{s}]") for s in ("script", "files")]


def copy_inputs(files, run, out, sby):
    """Copy the [files] entries into out as sby does. Directories are linked."""
    for entry in (e.strip() for e in files):
        if not entry or entry.startswith("#"):
            continue
        parts = entry.split()  # `src` or `dest src`
        if len(parts) > 2:
            sys.exit(f"{sby}: [files] entry not understood: {entry!r}")
        src = (run / parts[-1]).resolve()
        dst = out / (parts[0] if len(parts) == 2 else Path(parts[0]).name)
        if src.is_dir():
            if dst.is_symlink() or dst.exists():
                dst.unlink()
            dst.symlink_to(src)
        else:
            shutil.copyfile(src, dst)


def regenerate_asserts(out, args):
    """Regenerate the candidate files with the shared generator."""
    sys.path.insert(0, str(REPO / "internal_assertions_frontier_checks"))
    from _common.generate_internal_asserts import generate_assert_files
    names = dict(REGEN_FILES)
    for kv in args.regen_name:
        k, _, v = kv.partition("=")
        if k not in names or not v:
            sys.exit(f"--regen-name {kv!r}: expected KEY=FILE with KEY one of {', '.join(names)}")
        names[k] = v
    for k in ("gold", "gate"):
        if not (out / names[k]).exists():
            sys.exit(f"--regen: {names[k]} ({k}) is not among the run's inputs, see --regen-name")
    f = {k: out / v for k, v in names.items()}
    for k in ("expose", "decls", "ports_a", "ports_b", "asserts"):
        f[k].unlink(missing_ok=True)
    generate_assert_files(f["gold"], f["gate"], f["expose"], f["decls"], f["ports_a"], f["ports_b"],
                          f["asserts"], match_gate_wires=args.match_gate_wires,
                          const_candidates=args.const_candidates, fsm_candidates=args.fsm_candidates,
                          range_candidates=args.range_candidates,
                          guarded_candidates=args.guarded_candidates)


def write_comb_miter(out, miter, output_bits):
    """Write the miter with combinational assert blocks and the bit candidates. Returns (name, blocks, props)."""
    comb_name = Path(miter).stem + "_comb" + Path(miter).suffix
    bits_stem = Path(miter).stem + "_bits" if output_bits else None
    text, nconv, props = comb_miter((out / miter).read_text(), out, bits_stem)
    (out / comb_name).write_text(text)
    if not nconv:
        print(f"WARNING: no clocked assert block in {miter}; asserts used as they are", file=sys.stderr)
    if bits_stem:
        decls, cands = bit_candidate_files(props)
        (out / f"{bits_stem}_decls.vh").write_text(decls)
        (out / f"{bits_stem}.vh").write_text(cands)
        print(f"{len(props)} equality properties split into bit candidates ({bits_stem}.vh)", file=sys.stderr)
    return comb_name, nconv, props


def guard_lines(guards):
    return [ln for msg, sel in guards for ln in (f"log GUARD: {msg}", f"select -assert-none {sel}")]


def clock_guard_lines():
    return [f"log GUARD: {CLOCK_GUARD_MSG}", *CLOCK_GUARD]


def yosys_script(sby_script, miter, comb_name, allow_latches):
    """The sby script with the changes listed at the top of this file."""
    script, top, guarded = [], None, False
    guards = GUARDS + ([] if allow_latches else [LATCH_GUARD])
    for sby_line in sby_script:
        s = sby_line.strip()
        if s.startswith("clk2fflogic"):
            continue
        m = re.match(r"hierarchy\s.*-top\s+(\S+)", s)
        if m:
            top = m.group(1)
        if s.startswith("async2sync") and not guarded:
            script += guard_lines(guards)
            guarded = True
        if s.startswith("read_"):
            script.append(re.sub(rf"(?<![\w/.]){re.escape(miter)}(?![\w.])", comb_name, sby_line))
        else:
            script.append(sby_line)
    if not guarded:
        script += guard_lines(guards)
    if top is None:
        sys.exit("no `hierarchy -top` in the sby script")
    # again after prep, which turns processes into cells
    return [*script, f"prep -top {top}", *guard_lines(guards), *clock_guard_lines(), "dffunmap",
            "write_smt2 -wires model.smt2"]


def run_yosys(out):
    """Run build.ys in out. Returns (seconds, resource usage), exits if yosys fails."""
    model = out / "model.smt2"
    if model.exists():
        model.unlink()
    t0 = time.time()
    p = subprocess.Popen(["yosys", "-q", "-l", "build.log", "build.ys"], cwd=out,
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    _, status, ru = os.wait4(p.pid, 0)
    p.returncode = os.waitstatus_to_exitcode(status)
    err = p.stderr.read()
    secs = time.time() - t0
    if p.returncode:
        if model.exists():
            model.unlink()
        log = (out / "build.log").read_text() if (out / "build.log").exists() else ""
        guard = re.findall(r"GUARD: (.*)", log)
        failed_guard = guard[-1] if guard and "Assertion failed: selection" in (log + err) else None
        sys.exit(f"yosys failed ({p.returncode}) in {out}"
                 + (f": model has {failed_guard}" if failed_guard else f":\n{err.strip()[-2000:]}"))
    return secs, ru


def main():
    args = parse_args()
    run, out = Path(args.run_dir).resolve(), Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    sby_script, sby_files = read_sby(run / args.sby, args.task)
    copy_inputs(sby_files, run, out, run / args.sby)
    for rep in args.replace:
        name, path = rep.split("=", 1)
        shutil.copyfile(path, out / name)
    if args.regen:
        regenerate_asserts(out, args)
    comb_name, nconv, props = write_comb_miter(out, args.miter, args.output_bit_candidates)
    script = yosys_script(sby_script, args.miter, comb_name, args.allow_latches)
    (out / "build.ys").write_text("\n".join(script) + "\n")
    secs, ru = run_yosys(out)

    smt2 = (out / "model.smt2").read_text()
    info = {"run_dir": str(run), "sby": args.sby, "task": args.task, "regen": args.regen,
            "match_gate_wires": args.match_gate_wires,
            "const_candidates": args.const_candidates, "fsm_candidates": args.fsm_candidates,
            "range_candidates": args.range_candidates, "guarded_candidates": args.guarded_candidates,
            "replace": args.replace, "clocked_blocks_converted": nconv,
            "output_bit_candidates": len(props) if args.output_bit_candidates else None,
            "asserts": smt2.count("; yosys-smt2-assert "), "registers": smt2.count("; yosys-smt2-register "),
            "smt2_bytes": len(smt2), "build_secs": round(secs, 1), "peak_rss_mb": round(ru.ru_maxrss / 1024)}
    (out / "build.json").write_text(json.dumps(info, indent=1) + "\n")
    print(json.dumps(info))


if __name__ == "__main__":
    main()
