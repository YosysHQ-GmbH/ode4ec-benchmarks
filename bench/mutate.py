import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict, deque
from pathlib import Path

SEQ_BUILTIN = re.compile(
    r"\$(_(DFF|DFFE|SDFF|SDFFE|SDFFCE|ALDFF|ALDFFE|DFFSR|DFFSRE|DLATCH|DLATCHSR|SR|FF)_\w*"
    r"|dffe?|adffe?|sdffc?e?|dffsre?|aldffe?|a?dlatch|dlatchsr|sr|ff|mem\w*)$"
)


def liberty_cells(lib):
    text = Path(lib).read_text(errors="replace")
    heads = [
        (m.start(), m.group(1))
        for m in re.finditer(r'\bcell\s*\(\s*"?([\w$.]+)"?\s*\)\s*\{', text)
    ]
    out = {}
    for (start, name), (end, _) in zip(heads, heads[1:] + [(len(text), None)]):
        body = text[start:end]
        pins = re.findall(
            r'\bpin\s*\(\s*"?(\w+)"?\s*\)\s*\{[^{}]*?direction\s*:\s*"?output', body
        )
        seq = (
            re.search(r"\b(ff|ff_bank|latch|latch_bank|statetable)\s*\(", body)
            is not None
        )
        out["\\" + name] = (set(pins), seq)
    return out


def unread_nets(netlist, module, lib):
    text = Path(netlist).read_text()
    outputs = {}
    for m in re.finditer(r"\nmodule (\S+)\n(.*?)\nend\n", "\n" + text, re.DOTALL):
        outputs[m.group(1)] = set(
            re.findall(r"wire (?:width \d+ )?output \d+ \\(\S+)", m.group(2))
        )
    for k, (pins, _seq) in lib.items():
        outputs.setdefault(k, pins)
    body = re.search(
        rf"\nmodule \\{re.escape(module)}\n(.*?)\nend\n", "\n" + text, re.DOTALL
    ).group(1)

    def wires(sig):
        return {
            t for t in sig.replace("{", " ").replace("}", " ").split() if t[0] in "\\$"
        }

    read = {
        w
        for w in re.findall(
            r"wire (?:width \d+ )?(?:input|output|inout) \d+ (\S+)", body
        )
    }
    driven = {}
    for m in re.finditer(r"\n  cell (\S+) (\S+)\n(.*?)\n  end", body, re.DOTALL):
        for port, sig in re.findall(r"connect \\(\S+) (.+)", m.group(3)):
            if port in outputs.get(m.group(1), ()):
                driven.setdefault(sig.strip(), []).append((m.group(2), port))
            else:
                read |= wires(sig)
    for c in re.findall(r"\n  connect (.+)", body):
        read |= wires(c)
    unread = {
        (c.lstrip("\\"), p)
        for sig, cps in driven.items()
        for c, p in cps
        if not wires(sig) & read
    }
    silent = {
        n.lstrip("\\")
        for t, n in re.findall(r"\n  cell (\S+) (\S+)\n", body)
        if t
        in (
            "$print",
            "$check",
            "$assert",
            "$assume",
            "$cover",
            "$live",
            "$fair",
            "$scopeinfo",
        )
    }
    types = set(re.findall(r"\n  cell (\\\S+) ", body))
    unknown = sorted(t for t in types if t not in outputs)
    return unread, silent, unknown


def escape(name):
    return name if name.startswith("$") else "\\" + name


class FFDepth:
    def __init__(self, netlist_json, module, lib):
        mods = json.loads(Path(netlist_json).read_text())["modules"]
        mod = mods[module]

        def boxed(m):
            return any(
                str(mods[m].get("attributes", {}).get(a, "0")).strip("0")
                for a in ("blackbox", "whitebox")
            )

        sub = sorted(
            {
                c["type"]
                for c in mod["cells"].values()
                if c["type"] in mods and not boxed(c["type"])
            }
        )
        if sub:
            sys.exit(
                f"--max-ff-depth: {module} instantiates modules ({sub[:3]}), flatten it first"
            )
        self.cells = mod["cells"]
        self.seq = {
            n: int(
                bool(
                    SEQ_BUILTIN.match(c["type"])
                    or lib.get(escape(c["type"]), (None, False))[1]
                )
            )
            for n, c in self.cells.items()
        }
        self.undirected = set()
        drivers, inputs = defaultdict(list), {}
        for name, c in self.cells.items():
            dirs, ins = c.get("port_directions", {}), []
            for port, bits in c["connections"].items():
                d = dirs.get(port)
                if d is None:
                    self.undirected.add(c["type"])
                bits = [b for b in bits if isinstance(b, int)]
                if d in (None, "output", "inout"):
                    for b in bits:
                        drivers[b].append(name)
                if d in (None, "input", "inout"):
                    ins += bits
            inputs[name] = ins
        self.bit, self.cell = {}, {}
        q = deque()
        for p in mod["ports"].values():
            if p["direction"] in ("output", "inout"):
                for b in p["bits"]:
                    if isinstance(b, int) and b not in self.bit:
                        self.bit[b] = 0
                        q.append((0, b))
        while q:
            d, b = q.popleft()
            if d > self.bit[b]:
                continue
            for c in drivers.get(b, ()):
                if c in self.cell:
                    continue
                self.cell[c] = d
                nd = d + self.seq[c]
                for ib in inputs[c]:
                    if nd < self.bit.get(ib, nd + 1):
                        self.bit[ib] = nd
                        (q.appendleft if nd == d else q.append)((nd, ib))

    def of_mutation(self, m):
        cell = re.search(r"-cell (\S+)", m).group(1).lstrip("\\")
        port = re.search(r"-port (\S+)", m).group(1).lstrip("\\")
        bit = int(re.search(r"-portbit (\d+)", m).group(1))
        c = self.cells.get(cell)
        if c is None or cell not in self.cell:
            return None
        d = c.get("port_directions", {}).get(port)
        through = self.cell[cell] + self.seq[cell]
        if d == "input":
            return through
        b = c["connections"][port][bit]
        at = self.bit.get(b) if isinstance(b, int) else None
        if d == "output":
            return at
        return through if at is None else min(at, through)


def yosys(script, cwd, fatal=True):
    p = subprocess.run(
        ["yosys", "-q", "-p", script],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if p.returncode and fatal:
        sys.exit(f"yosys failed: {script}\n{p.stderr[-2000:]}")
    return p


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("netlist")
    ap.add_argument("out_dir")
    ap.add_argument("--module", required=True)
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument(
        "--wire", help="only mutations at cell ports connected to this wire"
    )
    ap.add_argument(
        "--liberty",
        help="liberty file for the pin directions of library cells (if the netlist "
        "does not define them)",
    )
    ap.add_argument(
        "--keep-unobservable",
        action="store_true",
        help="keep mutations of nets nothing reads and of cells without outputs (equivalent by "
        "construction)",
    )
    ap.add_argument(
        "--max-ff-depth",
        type=int,
        help="only mutations with a path to a module output through at most this many flip-flops, "
        "latches or memories (0: a combinational path); needs a flat module",
    )
    args = ap.parse_args()
    src, out = Path(args.netlist).resolve(), Path(args.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    flt = f" -wire {args.wire}" if args.wire else ""
    read = (
        f"read_liberty -lib {Path(args.liberty).resolve()}; " if args.liberty else ""
    ) + f"read_rtlil {src}"
    lib = liberty_cells(args.liberty) if args.liberty else {}
    sel, depth, notes = "", None, []
    if args.max_ff_depth is not None:
        yosys(f"{read}; write_json {out / 'netlist.json'}", out)
        depth = FFDepth(out / "netlist.json", args.module, lib)
        (out / "netlist.json").unlink()
        if depth.undirected:
            print(
                f"WARNING: --max-ff-depth: port directions unknown for {len(depth.undirected)} cell types "
                f"({sorted(depth.undirected)[:3]}); their ports count as inputs and outputs",
                file=sys.stderr,
            )
        hist = defaultdict(int)
        for c in depth.cells:
            hist[depth.cell.get(c, "none")] += 1
        notes.append(
            "cells by sequential cells to an output (none: no path): "
            + ", ".join(
                f"{k}: {hist[k]}" for k in sorted(hist, key=lambda k: (k == "none", k))
            )
        )
        near = sorted(c for c, d in depth.cell.items() if d <= args.max_ff_depth)
        notes.append(
            f"--max-ff-depth {args.max_ff_depth}: {len(near)} of {len(depth.cells)} cells"
        )
        print("\n".join(notes))
        if not near:
            sys.exit("no cell within --max-ff-depth of an output")
        (out / "near.sel").write_text(
            "".join(f"{escape(args.module)}/{escape(c)}\n" for c in near)
        )
        sel = f"select -read {out / 'near.sel'}; "
    oversample = 1 if args.keep_unobservable and depth is None else 10
    yosys(
        f"{read}; {sel}mutate -list {args.n * oversample} -seed {args.seed} -module {args.module}{flt} "
        f"-o {out / 'list.ys'}",
        out,
    )
    muts = [
        ln.strip()
        for ln in (out / "list.ys").read_text().split("\n")
        if ln.strip().startswith("mutate ")
    ]
    if depth is not None:
        n_all = len(muts)
        muts = [
            m
            for m in muts
            if (d := depth.of_mutation(m)) is not None and d <= args.max_ff_depth
        ]
        print(f"{n_all} sampled, {len(muts)} within --max-ff-depth")
    if not args.keep_unobservable:
        unread, silent, unknown = unread_nets(src, args.module, lib)
        if unknown:
            print(
                f"WARNING: pin directions unknown for {len(unknown)} cell types ({unknown[:3]}); pass --liberty. "
                "Unobservable mutations of their outputs are not filtered.",
                file=sys.stderr,
            )

        def useful(m):
            cell = re.search(r"-cell (\S+)", m).group(1).lstrip("\\")
            port = re.search(r"-port (\S+)", m).group(1)
            return (cell, port) not in unread and cell not in silent

        n_all = len(muts)
        muts = [m for m in muts if useful(m)]
        print(
            f"{n_all} sampled, {len(muts)} kept (dropped mutations nothing can observe)"
        )
    if not muts:
        sys.exit("no mutation candidates")
    n, malformed = 0, 0
    with open(out / "mutations.ys", "w") as fh:
        fh.writelines(f"# {note}\n" for note in notes)
        for m in muts:
            if n == args.n:
                break
            il = out / f"m{n + 1:02d}.il"
            p = yosys(
                f"{read}; {m}; check -assert {args.module}; write_rtlil {il}",
                out,
                fatal=False,
            )
            if p.returncode:
                malformed += 1
                fh.write(f"# skipped, malformed (check -assert): {m}\n")
                continue
            n += 1
            if depth is not None:
                fh.write(
                    f"# m{n:02d}: {depth.of_mutation(m)} sequential cells to an output\n"
                )
            fh.write(f"m{n:02d}: {m}\n")
    if malformed:
        print(f"{malformed} malformed mutants skipped (see mutations.ys)")
    print(f"{n} mutants in {out}")


if __name__ == "__main__":
    main()
