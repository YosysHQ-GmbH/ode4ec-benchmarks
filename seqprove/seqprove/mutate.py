#!/usr/bin/env python3
"""Mutants of a netlist for non-vacuity tests, using yosys' `mutate` (the mcy mechanism).

usage: mutate.py IN.il OUT_DIR --module gate_top [--n 20] [--seed 1] [--wire NAME]
                 [--case "BENCH RUN asserts=new" [--replace-name gate.il]]

Writes OUT_DIR/mNN.il, mutations.ys (the applied commands) and, with --case, cases.txt for run_bench.py.
A mutant may be equivalent (redundant logic), so cross-check a PASS with an independent engine.
Without cell port directions `mutate` rewires the net of an input pin, so --liberty also loads the cells,
and a mutant that fails `check -assert` is skipped.
"""
import argparse
import subprocess
import sys
from pathlib import Path


def liberty_outputs(lib):
    """{cell type: output pin names} from a liberty file."""
    import re
    text = Path(lib).read_text(errors="replace")
    heads = [(m.start(), m.group(1)) for m in re.finditer(r'\bcell\s*\(\s*"?([\w$.]+)"?\s*\)\s*\{', text)]
    out = {}
    for (start, name), (end, _) in zip(heads, heads[1:] + [(len(text), None)]):
        pins = re.findall(r'\bpin\s*\(\s*"?(\w+)"?\s*\)\s*\{[^{}]*?direction\s*:\s*"?output', text[start:end])
        out["\\" + name] = set(pins)
    return out


def unread_nets(netlist, module, liberty=None):
    """Cell outputs in module that nothing reads, e.g. insbuf copies. Mutating them is useless."""
    import re
    text = Path(netlist).read_text()
    outputs = {}                                    # cell type -> output port names
    for m in re.finditer(r"\nmodule (\S+)\n(.*?)\nend\n", "\n" + text, re.DOTALL):
        outputs[m.group(1)] = set(re.findall(r"wire (?:width \d+ )?output \d+ \\(\S+)", m.group(2)))
    if liberty:
        for k, v in liberty_outputs(liberty).items():
            outputs.setdefault(k, v)
    body = re.search(rf"\nmodule \\{re.escape(module)}\n(.*?)\nend\n", "\n" + text, re.DOTALL).group(1)
    # A net counts as read if any part of its wire is. This keeps too many mutants rather than too few: a
    # useless mutant is harmless, a dropped observable one weakens the test.
    def wires(sig):
        return {t for t in sig.replace("{", " ").replace("}", " ").split() if t[0] in "\\$"}
    read = {w for w in re.findall(r"wire (?:width \d+ )?(?:input|output|inout) \d+ (\S+)", body)}
    driven = {}
    for m in re.finditer(r"\n  cell (\S+) (\S+)\n(.*?)\n  end", body, re.DOTALL):
        for port, sig in re.findall(r"connect \\(\S+) (.+)", m.group(3)):
            if port in outputs.get(m.group(1), ()):
                driven.setdefault(sig.strip(), []).append((m.group(2), port))
            else:
                read |= wires(sig)
    for c in re.findall(r"\n  connect (.+)", body):
        read |= wires(c)
    unread = {(c.lstrip("\\"), p) for sig, cps in driven.items() for c, p in cps if not wires(sig) & read}
    # cells without logic outputs ($print, formal cells)
    silent = {n.lstrip("\\") for t, n in re.findall(r"\n  cell (\S+) (\S+)\n", body)
              if t in ("$print", "$check", "$assert", "$assume", "$cover", "$live", "$fair", "$scopeinfo")}
    types = set(re.findall(r"\n  cell (\\\S+) ", body))     # library cell types, not internal $cells
    unknown = sorted(t for t in types if t not in outputs)
    return unread, silent, unknown


def yosys(script, cwd, fatal=True):
    p = subprocess.run(["yosys", "-q", "-p", script], cwd=cwd, capture_output=True, text=True, check=False)
    if p.returncode and fatal:
        sys.exit(f"yosys failed: {script}\n{p.stderr[-2000:]}")
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("netlist")
    ap.add_argument("out_dir")
    ap.add_argument("--module", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--wire", help="only mutations at cell ports connected to this wire")
    ap.add_argument("--case", help='"BENCH RUN [options]" prefix for cases.txt')
    ap.add_argument("--replace-name", default="gate.il", help="the run's gate input that a mutant replaces")
    ap.add_argument("--liberty", help="liberty file for the pin directions of library cells (if the netlist "
                                      "does not define them)")
    ap.add_argument("--keep-unobservable", action="store_true",
                    help="keep mutations of nets nothing reads and of cells without outputs (equivalent by "
                         "construction)")
    args = ap.parse_args()
    src, out = Path(args.netlist).resolve(), Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    flt = f" -wire {args.wire}" if args.wire else ""
    # library cells first, so that mutate knows the port directions
    read = (f"read_liberty -lib {Path(args.liberty).resolve()}; " if args.liberty else "") + f"read_rtlil {src}"
    oversample = 1 if args.keep_unobservable else 10
    yosys(f"{read}; mutate -list {args.n * oversample} -seed {args.seed} -module {args.module}{flt} "
          f"-o {out / 'list.ys'}", out)
    muts = [ln.strip() for ln in (out / "list.ys").read_text().split("\n") if ln.strip().startswith("mutate ")]
    if not args.keep_unobservable:
        import re
        unread, silent, unknown = unread_nets(src, args.module, args.liberty)
        if unknown:
            print(f"WARNING: pin directions unknown for {len(unknown)} cell types ({unknown[:3]}); pass --liberty. "
                  "Unobservable mutations of their outputs are not filtered.", file=sys.stderr)
        def useful(m):
            cell = re.search(r"-cell (\S+)", m).group(1).lstrip("\\")
            port = re.search(r"-port (\S+)", m).group(1)
            return (cell, port) not in unread and cell not in silent
        n_all = len(muts)
        muts = [m for m in muts if useful(m)]
        print(f"{n_all} sampled, {len(muts)} kept (dropped mutations nothing can observe)")
    if not muts:
        sys.exit("no mutation candidates")
    cases, n, malformed = [], 0, 0
    with open(out / "mutations.ys", "w") as fh:
        for m in muts:
            if n == args.n:
                break
            il = out / f"m{n + 1:02d}.il"
            p = yosys(f"{read}; {m}; check -assert {args.module}; write_rtlil {il}", out, fatal=False)
            if p.returncode:
                malformed += 1
                fh.write(f"# skipped, malformed (check -assert): {m}\n")
                continue
            n += 1
            fh.write(f"m{n:02d}: {m}\n")
            if args.case:
                cases.append(f"{args.case} name=m{n:02d} replace={args.replace_name}={il}")
    if malformed:
        print(f"{malformed} malformed mutants skipped (see mutations.ys)")
    if cases:
        (out / "cases.txt").write_text("\n".join(cases) + "\n")
    print(f"{n} mutants in {out}")


if __name__ == "__main__":
    main()
