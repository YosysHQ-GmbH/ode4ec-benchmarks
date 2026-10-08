#!/usr/bin/env python3
"""Markdown table of seq_prove results per case across run_bench tags (latest row per case and tag).

usage: compare.py TAG [TAG ...] [--old runs/ab_old/results.csv]

--old: a CSV `bench,run,variant,result,secs` from the old xorgrid_incremental/seq_prove.py
(result "x/y" = proven asserts, TIMEOUT, ERROR), shown as the first column.
"""
import argparse
import csv
from pathlib import Path

RUNS = Path(__file__).resolve().parent.parent / "runs"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tags", nargs="+")
    ap.add_argument("--old")
    args = ap.parse_args()
    data = {}
    for tag in args.tags:
        rows = {}
        with open(RUNS / tag / "results.csv") as fh:
            for r in csv.DictReader(fh):
                if r["tool"] == "seq_prove":
                    rows[(r["bench"], r["run"], r["variant"])] = r
        data[tag] = rows
    old = {}
    if args.old:
        with open(args.old) as fh:
            for r in csv.DictReader(fh):
                y = r["result"].split("/")
                res = "PASS*" if len(y) == 2 and y[0] == y[1] else r["result"]
                old[(r["bench"], r["run"], r["variant"])] = f"{res} {r['secs']}s"
    keys = list(dict.fromkeys(k for rows in data.values() for k in rows))

    head = ["bench", "run", "asserts (L0/L1)"] + (["old seq_prove"] if old else []) + args.tags
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for k in keys:
        # the L0/L1 split of the tag with the most layer-1 asserts
        f = max((data[t].get(k, {}) for t in args.tags), key=lambda r: int(r.get("L1") or 0))
        cells = [k[0], k[1], f"{f.get('asserts', '')} ({f.get('L0', '')}/{f.get('L1', '')})"]
        if old:
            cells.append(old.get(k, "-"))
        for tag in args.tags:
            r = data[tag].get(k)
            cells.append(f"{r['result']} {r['wall_secs']}s" if r else "-")
        print("| " + " | ".join(cells) + " |")
    if old:
        print("\n`PASS*` for the old script = all asserts proven; it has no separate property/candidate report.")


if __name__ == "__main__":
    main()
