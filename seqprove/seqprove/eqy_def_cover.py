#!/usr/bin/env python3
"""Non-vacuity check of an eqy PASS: can every gold output port take a defined (non-x) value?

usage: eqy_def_cover.py EQY_WORKDIR [--depth 25] [--engine "smtbmc yices"] [--timeout 600] [--jobs 4]

eqy compares an output only where gold is defined (`gold === x || gold === gate`), so a gold output that is
always x is never compared. For each partition this runs sby cover with eqy's COVER_DEF_GOLD_OUTPUTS on the
output ports, using the partition's own strategy script. An output not reached within --depth leaves the
PASS unverified, which is not a proof that it is never defined. Exit code 1 if any output is not reached or
a run failed.
"""
import argparse
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


def gold_outputs(wd):
    return {ln.split()[1] for ln in (wd / "gold.ids").read_text().split("\n")
            if ln.startswith("top ") and "P=O" in ln.split()}


def strategy_script(wd, part):
    """The [script] of the sby strategy eqy ran on this partition."""
    for sby in sorted((wd / "strategies" / part).glob("*/*.sby")):
        text = sby.read_text()
        m = re.search(r"^\[script\]\n(.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
        if m:
            return m.group(1)
    return None


def cover_partition(wd, sv, outputs, args, out):
    part = sv.stem
    text = sv.read_text()
    block = re.search(r"`ifdef COVER_DEF_GOLD_OUTPUTS\n(.*?)`endif", text, re.DOTALL)
    if not block:
        return part, {}, "no COVER_DEF_GOLD_OUTPUTS block"
    keep = [ln for ln in block.group(1).split("\n")
            if (m := re.search(r"\\__po_(\S+)__gold_cover ", ln)) and m.group(1) in outputs]
    names = [re.search(r"\\__po_(\S+)__gold_cover ", ln).group(1) for ln in keep]
    if not names:
        return part, {}, None
    script = strategy_script(wd, part)
    if script is None:
        return part, dict.fromkeys(names, "ERROR"), "no sby strategy script for this partition"
    d = out / part
    d.mkdir(parents=True, exist_ok=True)
    (d / "part.sv").write_text(text[:block.start(1)] + "\n".join(keep) + "\n" + text[block.end(1):])
    (d / "part.il").write_text((wd / "partitions" / f"{part}.il").read_text())
    script = script.replace("-D CHECK_OUTPUTS", "-D COVER_DEF_GOLD_OUTPUTS")
    script = re.sub(r"\S*partitions/" + re.escape(part) + r"\.(sv|il)", r"part.\1", script)
    (d / "cover.sby").write_text(f"[options]\nmode cover\ndepth {args.depth}\ntimeout {args.timeout}\n\n"
                                 f"[engines]\n{args.engine}\n\n[script]\n{script}\n[files]\npart.sv\npart.il\n")
    subprocess.run(["sby", "-f", "cover.sby"], cwd=d, capture_output=True, text=True, check=False)
    log = (d / "cover" / "logfile.txt")
    if not log.exists():
        return part, dict.fromkeys(names, "ERROR"), "sby wrote no log"
    lines = log.read_text().split("\n")
    res = {}
    for n in names:
        tag = f"__po_{n}__gold_cover"
        tag_flat = re.sub(r"[^A-Za-z0-9_]", "_", tag)
        hit = [ln for ln in lines if ("Reached cover" in ln or "Unreached cover" in ln)
               and (tag in ln or tag_flat in ln)]
        res[n] = ("NOT reached" if any("Unreached" in ln for ln in hit) else
                  "reached" if hit else "ERROR")
    err = None if all(v != "ERROR" for v in res.values()) else f"see {log}"
    return part, res, err


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("workdir", type=Path)
    ap.add_argument("--depth", type=int, default=25)
    ap.add_argument("--engine", default="smtbmc yices")
    ap.add_argument("--timeout", type=int, default=600)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--out", type=Path, help="work dir (default WORKDIR/../def_cover)")
    args = ap.parse_args()
    wd = args.workdir.resolve()
    out = (args.out or wd.parent / "def_cover").resolve()
    outputs = gold_outputs(wd)
    svs = sorted((wd / "partitions").glob("*.sv"))
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        results = list(ex.map(lambda sv: cover_partition(wd, sv, outputs, args, out), svs))
    seen, bad = {}, 0
    for part, res, err in results:
        for n, r in sorted(res.items()):
            seen[n] = r
            print(f"{r:12s} {n}  ({part})")
        if err:
            print(f"ERROR        {part}: {err}")
            bad += 1
    missing = sorted(outputs - set(seen))
    for n in missing:
        print(f"NOT COVERED  {n}  (in no partition's covers)")
    c = {k: sum(1 for v in seen.values() if v == k) for k in ("reached", "NOT reached", "ERROR")}
    print(f"\n{len(outputs)} gold output bits: {c['reached']} defined within {args.depth} steps, "
          f"{c['NOT reached']} not, {c['ERROR'] + len(missing)} errors / not covered")
    sys.exit(1 if bad or missing or c["NOT reached"] or c["ERROR"] else 0)


if __name__ == "__main__":
    main()
