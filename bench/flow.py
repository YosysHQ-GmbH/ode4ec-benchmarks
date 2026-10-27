import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import checks
import runner
from design import point_name

HERE = Path(__file__).resolve().parent
LIBERTY = HERE / "platforms" / "sky130hd" / "sky130_fd_sc_hd__tt_025C_1v80.lib"
ORFS = Path(os.environ.get("ORFS_HOME", HERE / "orfs"))
CELLS = {
    "tie": "sky130_fd_sc_hd__conb_1",
    "clkbuf": "sky130_fd_sc_hd__clkbuf_1",
    "buf": "sky130_fd_sc_hd__buf_1",
}


def read_cmds(d, point, bdir):
    src, top = d["source"], d["top"]
    base, hdl = (bdir / "gen", {}) if "generate" in src else (d["dir"], point)
    if src["frontend"] == "ghdl":
        files = [str(base / f) for f in src["files"]]
        gen = [f"-g{k}={v}" for k, v in sorted(hdl.items())]
        return [
            "plugin -i ghdl",
            " ".join(["ghdl", *src["args"], *gen, *files, "-e", top]),
        ]
    defs = [f"-D {k}={v}" if v != "" else f"-D {k}" for k, v in src["defines"].items()]
    gen = [f"-G {k}={v}" for k, v in sorted(hdl.items())]
    files = (
        ["-F", str(base / src["flist"])]
        if "flist" in src
        else [str(base / f) for f in src["files"]]
    )
    return [
        "plugin -i slang",
        " ".join(["read_slang", *src["args"], *defs, *gen, *files, "--top", top]),
    ]


def sdc_text(d):
    clks = d["clocks"] or [{"name": "vclk", "period_ns": 10, "virtual": True}]
    lines = [
        f"create_clock -name {c['name']} -period {c['period_ns']}"
        + ("" if c.get("virtual") else f" [get_ports {{{c['name']}}}]")
        for c in clks
    ]
    real = " ".join(c["name"] for c in d["clocks"])
    ins = (
        f"[remove_from_collection [all_inputs] [get_ports {{{real}}}]]"
        if real
        else "[all_inputs]"
    )
    creates, clk = "\n".join(lines), clks[0]["name"]
    return f"""{creates}
set_input_delay -clock {clk} 1.0 {ins}
set_output_delay -clock {clk} 1.0 [all_outputs]
"""


def script(text):
    return [ln for ln in text.split("\n") if ln]


def orfs_work(bdir):
    safe = re.sub(r"[^\w.-]", "_", bdir.name)
    return (
        bdir.parent
        / "_orfs"
        / f"{safe}_{hashlib.sha256(bdir.name.encode()).hexdigest()[:6]}"
    )


def steps(d, point, flavor, bdir):
    top, lib = d["top"], LIBERTY
    read = "\n".join(read_cmds(d, point, bdir))
    first = {}
    if "generate" in d["source"]:
        subst = {"{design}": str(d["dir"]), "{out}": str(bdir / "gen")}
        subst.update({f"{{{k}}}": str(v) for k, v in point.items()})
        cmd = []
        for a in d["source"]["generate"]:
            for k, v in subst.items():
                a = a.replace(k, v)
            cmd.append(a)
        if left := sorted(set(re.findall(r"\{\w+\}", " ".join(cmd)))):
            raise RuntimeError(
                f"generate: no value for {left} at point {point_name(point)}"
            )
        first = {"generate": {"files": {}, "cmd": cmd}}
    init = "setattr -unset init" if d["power_up"]["gate"] == "free" else ""
    gold = script(f"""
{read}
hierarchy -check -top {top}
memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
rename {top} gold_top
flatten
write_rtlil gold.il
""")
    if flavor == "yosys":
        synth = script(f"""
{read}
hierarchy -top {top}
chformal -remove
synth -run :check
stat
dfflibmap -liberty {lib}
dfflegalize -cell $_DLATCH_?_ x
abc -liberty {lib}
splitnets
setundef -zero
opt
hilomap -hicell {CELLS["tie"]} HI -locell {CELLS["tie"]} LO
clkbufmap -buf {CELLS["clkbuf"]} X
insbuf -buf {CELLS["buf"]} A X
opt_clean -purge
flatten
check -mapped -noinit
tee -o stat.txt stat -liberty {lib}
rename {top} gate_top
flatten
{init}
write_rtlil gate.il
""")
        return {**first, "gold": gold, "synth": synth}
    work = orfs_work(bdir)
    netlist = work / "results" / "sky130hd" / top / "base" / "1_2_yosys.v"
    pre = script(f"""
{read}
hierarchy -check -top {top}
chformal -remove
flatten
opt_clean -purge
simplemap t:$bwmux
opt_clean -purge
write_verilog -noattr {work}/pre_synth.v
""")
    extra = "".join(f"{ln}\n" for ln in d["flows"]["orfs"]["config"])
    config = f"""export DESIGN_NAME = {top}
export PLATFORM = sky130hd
export VERILOG_FILES = {work}/pre_synth.v
export SDC_FILE = {work}/constraint.sdc
{extra}"""
    orfs = {
        "files": {f"{work}/config.mk": config, f"{work}/constraint.sdc": sdc_text(d)},
        "cmd": [
            "make",
            "-C",
            str(ORFS / "flow"),
            f"DESIGN_CONFIG={work}/config.mk",
            f"WORK_HOME={work}",
            f"YOSYS_EXE={shutil.which('yosys')}",
            str(netlist),
        ],
    }
    gate = script(f"""
read_liberty -lib {lib}
plugin -i slang
read_slang {netlist} --top {top}
hierarchy -check -top {top}
flatten
opt_clean -purge
check -mapped -noinit
tee -o stat.txt stat -liberty {lib}
rename {top} gate_top
{init}
select gate_top
write_rtlil -selected gate.il
""")
    return {**first, "gold": gold, "pre": pre, "orfs": orfs, "gate": gate}


def tool_versions(flavor):
    v = subprocess.run(
        ["yosys", "-V"], capture_output=True, text=True, check=True
    ).stdout.strip()
    if flavor == "orfs":
        git = [
            "git",
            "-C",
            str(ORFS),
            "describe",
            "--always",
            "--dirty",
            "--abbrev=7",
            "--exclude=*",
        ]
        v += (
            "; ORFS "
            + subprocess.run(
                git, capture_output=True, text=True, check=False
            ).stdout.strip()
        )
    return v


NOT_IN_BUNDLE = ("flows", "params", "points", "ladders", "exercises", "cover")


def build_key(d, step_list, version):
    h = hashlib.sha256()
    h.update(
        json.dumps(
            {k: v for k, v in d.items() if k not in NOT_IN_BUNDLE},
            sort_keys=True,
            default=str,
        ).encode()
    )
    h.update(json.dumps(step_list, sort_keys=True).encode())
    h.update(version.encode())
    src = d["source"]
    if "generate" in src:
        files = sorted(
            f.name
            for f in d["dir"].iterdir()
            if f.is_file() and f.name != "design.toml"
        )
    else:
        files = [src["flist"]] if "flist" in src else src["files"]
    for f in files:
        h.update((d["dir"] / f).read_bytes())
    return h.hexdigest()[:16]


class Unsupported(Exception):
    """The gold design has several clock nets or latches."""


LATCHES = re.compile(r"^\$(_?dlatch\w*|adlatch)$", re.IGNORECASE)


def unsupported(il):
    clocks, latches, kind = set(), 0, None
    for ln in Path(il).read_text().split("\n"):
        if ln.startswith("  cell "):
            kind = ln.split()[1]
            latches += bool(LATCHES.match(kind))
        elif (
            kind
            and "dff" in kind.lower()
            and ln.startswith(("    connect \\CLK ", "    connect \\C "))
        ):
            clocks.add(ln.split(None, 2)[2])
        elif ln.startswith("  end"):
            kind = None
    why = []
    if len(clocks) > 1:
        why.append(f"{len(clocks)} clock nets ({', '.join(sorted(clocks)[:4])})")
    if latches:
        why.append(f"{latches} latches")
    return "; ".join(why)


def conflicts(bdir, timeout):
    why = []
    for name, pre in (("gold.il", ""), ("gate.il", f"read_liberty -lib {LIBERTY}; ")):
        cmd, oomf = runner.capped(["yosys", "-qp", f"{pre}read_rtlil {name}; check"])
        oom0 = runner.oom_kills()
        p = subprocess.run(
            cmd, cwd=bdir, capture_output=True, text=True, timeout=timeout, check=False
        )
        if runner.oom_killed(oomf, oom0) or p.returncode:
            raise RuntimeError(
                f"check of {name} failed: {(p.stdout + p.stderr).strip()[-200:]}"
            )
        bits = re.findall(
            r"multiple conflicting drivers for (\S+)", p.stdout + p.stderr
        )
        if wires := sorted({w.rstrip(":") for w in bits}):
            why.append(
                f"{name}: conflicting drivers on {len(bits)} bits of {len(wires)} wires "
                f"({', '.join(wires[:2])})"
            )
    return "; ".join(why)


def build(d, point, flavor, root, rebuild=False):
    bdir = root / d["name"] / f"{point_name(point)}_{flavor}"
    step_list = steps(d, point, flavor, bdir)
    version = tool_versions(flavor)
    key = build_key(d, step_list, version)
    case_file = bdir / "case.json"
    if (
        not rebuild
        and case_file.exists()
        and json.loads(case_file.read_text()).get("build_key") == key
    ):
        return bdir
    for gone in (orfs_work(bdir), bdir / "gen"):
        shutil.rmtree(gone, ignore_errors=True)
    if flavor == "orfs":
        orfs_work(bdir).mkdir(parents=True)
    bdir.mkdir(parents=True, exist_ok=True)
    if "generate" in d["source"]:
        (bdir / "gen").mkdir()
    for f in ("case.json", "gold.il", "gate.il"):
        (bdir / f).unlink(missing_ok=True)
    env = {**os.environ, **d["source"]["env"]}
    t0 = time.time()
    for name, step in step_list.items():
        if isinstance(step, list):
            (bdir / f"{name}.ys").write_text("\n".join(step) + "\n")
            argv = ["yosys", "-ql", f"{name}.log", f"{name}.ys"]
        else:
            for f, text in step["files"].items():
                Path(bdir, f).write_text(text)
            argv = step["cmd"]
        cmd, oomf = runner.capped(argv)
        oom0 = runner.oom_kills()
        with open(bdir / f"{name}.out", "w") as fh:
            p = subprocess.Popen(
                cmd,
                cwd=bdir,
                env=env,
                stdout=fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            try:
                p.wait(timeout=d["limits"]["build_timeout"])
            except subprocess.TimeoutExpired:
                runner.kill_tree(p.pid)
                p.wait()
                raise RuntimeError(
                    f"{name}: timeout after {d['limits']['build_timeout']} s"
                ) from None
        if runner.oom_killed(oomf, oom0):
            raise RuntimeError(f"{name}: OOM, killed by the memory cap")
        if p.returncode:
            log = next(
                (
                    f.read_text(errors="replace")
                    for f in (bdir / f"{name}.log", bdir / f"{name}.out")
                    if f.exists()
                ),
                "",
            )
            raise RuntimeError(
                f"{name}: {argv[0]} failed: "
                + " | ".join(re.findall(r"ERROR.*", log)[-2:] or [log[-300:]])
            )
        if name == "gold" and (why := unsupported(bdir / "gold.il")):
            raise Unsupported(f"unsupported: {why}")
    if why := conflicts(bdir, d["limits"]["build_timeout"]):
        raise RuntimeError(f"malformed netlist (benchmark defect): {why}")
    gold, gate = (
        {p["name"]: p for p in checks.ports(bdir / f"{s}.il", f"{s}_top")}
        for s in ("gold", "gate")
    )
    if gold != gate:
        raise RuntimeError(
            f"gold and gate ports differ (benchmark defect): {checks.port_diff(gold, gate)}"
        )
    (bdir / "cells.lib").unlink(missing_ok=True)
    (bdir / "cells.lib").symlink_to(LIBERTY)
    case = {
        "design": d["name"],
        "point": point,
        "flavor": flavor,
        "top": d["top"],
        "ports": list(gold.values()),
        "clocks": d["clocks"],
        "resets": d["resets"],
        "compare": d["compare"],
        "power_up": d["power_up"],
        "limits": d["limits"],
        "tools": version,
        "build_secs": round(time.time() - t0, 1),
        "build_key": key,
        "input_hash": checks.input_hash(bdir),
    }
    case_file.write_text(json.dumps(case, indent=1) + "\n")
    return bdir
