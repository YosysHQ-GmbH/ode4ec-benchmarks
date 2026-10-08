# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "matplotlib>=3.11.1",
# ]
# ///
"""Frontier figure: time to verdict against design size (cells) per scaling axis, one line per tool.

usage: uv run plot_frontier.py [--seq TAG] [--eqy TAG] [--out DIR] [--theme light|dark]

seq_prove and eqy come from frontier.py runs (seqprove/runs/TAG/frontier.csv). Plain sby comes from the sby
frontier of internal_assertions_frontier_checks (BENCH/run/results.csv, plain miter MI), using the prove-mode
engine with the largest PASS on the axis. Each engine ran its own search, so taking the best engine per size
would mix searches that visited different sizes. Lines join the PASSes. A hollow mark on a dashed line is a
size without a verdict within the time limit.
Writes DIR/frontier.png (one panel per axis), DIR/frontier_all.png (all axes in one plot) and DIR/frontier.csv.
"""
import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter

from plot_compare import RUNS, THEMES, TOOLS, marker, style, write_csv

FRONTIER = RUNS.parent.parent / "internal_assertions_frontier_checks"
PROVE_ENGINES = ("abc-pdr", "aiger-suprove", "aiger-rIC3")


def verdict(result):
    return result if result in ("PASS", "FAIL", "ERROR") else "UNKNOWN"


def frontier_points(tag, want_eqy):
    """{(bench, axis): [point]} from a frontier.py run, without SETUP_ERROR rows."""
    f = RUNS / tag / "frontier.csv"
    out = defaultdict(list)
    if not f.exists():
        print(f"warning: {f} not found, skipped")
        return out, {}
    limits = {}
    with open(f) as fh:
        for r in csv.DictReader(fh):
            if (r["variant"] == "eqy") != want_eqy or not r["cells"] or r["result"] == "SETUP_ERROR":
                continue
            limits[(r["bench"], r["axis"])] = float(r["timeout"])
            out[(r["bench"], r["axis"])].append({"cells": int(r["cells"]), "secs": float(r["total_secs"] or 0),
                                                 "result": verdict(r["result"]), "run": r["run"]})
    return out, limits


def plain_points(bench, axis):
    """(engine, points) of the plain miter: the prove-mode engine with the largest PASS on the axis (the
    faster one on a tie), with every size its search visited."""
    f = FRONTIER / bench / "run" / "results.csv"
    by_engine = defaultdict(list)
    if f.exists():
        with open(f) as fh:
            for r in csv.DictReader(fh):
                if r["benchmark"] == axis and r["task"] in PROVE_ENGINES and r["cells_miter"]:
                    by_engine[r["task"]].append({"cells": int(r["cells_miter"]), "run": r["name"],
                                                 "secs": float(r["clock_secs_miter"] or 0),
                                                 "result": verdict(r["result_miter"])})
    if not by_engine:
        return None, []

    def reach(engine):
        ok = [p for p in by_engine[engine] if p["result"] == "PASS"]
        top = max(ok, key=lambda p: p["cells"]) if ok else None
        return (top["cells"], -top["secs"]) if top else (0, 0)

    best = max(sorted(by_engine), key=reach)
    return (best if reach(best)[0] else f"no prove-mode PASS ({best} shown)"), by_engine[best]


def fmt_secs(v, _pos=None):
    return f"{v:g} s" if v < 1 else f"{v:,.0f} s"


def format_axes(ax, th, ytop):
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_ylim(0.1, ytop)
    ax.yaxis.set_major_formatter(FuncFormatter(fmt_secs))
    lo, hi = ax.get_xlim()      # 1-2-5 ticks only up to about 2.5 decades
    ax.xaxis.set_major_locator(LogLocator(base=10, subs=(1.0, 2.0, 5.0) if hi / lo < 300 else (1.0, 3.0)))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.xaxis.set_minor_formatter(NullFormatter())
    ax.grid(which="major", color=th["grid"], lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_xlabel("cells of the scaled design (gate netlist)", fontsize=8.5)
    ax.set_ylabel("time to verdict", fontsize=8.5)


def legend(fig, th):
    tool_h = [Line2D([], [], color=th["series"][j], lw=1.6, marker="o", markersize=6, label=n)
              for j, (_, n) in enumerate(TOOLS)]
    res_h = [Line2D([], [], linestyle="none", markersize=6, label=lab, **marker({"result": r}, th["ink2"], th))
             for r, lab in (("PASS", "PASS"), ("UNKNOWN", "no verdict within the limit"), ("ERROR", "ERROR"))]
    leg = fig.legend(handles=tool_h + res_h, ncol=6, loc="upper left",
                     bbox_to_anchor=(0.01, 1 - 0.45 / fig.get_figheight()), frameon=False, fontsize=8.5)
    for t in leg.get_texts():
        t.set_color(th["ink"])


def short(key):
    return f"{key[0].removeprefix('ol_')} {key[1].removesuffix(' Scaling').lower()}"


def draw_combined(panels, data, limits, th, out):
    """All axes in one plot: a thin line per tool and axis through the PASSes, labelled at the largest."""
    fig, ax = plt.subplots(figsize=(10, 6.8))
    fig.subplots_adjust(left=0.08, right=0.97, top=1 - 0.95 / 6.8, bottom=0.09)
    for j, (kind, _name) in enumerate(TOOLS):
        color = th["series"][j]
        for key in panels:
            pts = sorted(data[kind].get(key, []), key=lambda p: p["cells"])
            ok = [p for p in pts if p["result"] == "PASS"]
            if ok:
                ax.plot([p["cells"] for p in ok], [max(p["secs"], 0.1) for p in ok], color=color, lw=1, alpha=0.6,
                        zorder=2)
                ax.annotate(short(key), (ok[-1]["cells"], max(ok[-1]["secs"], 0.1)), xytext=(5, -4),
                            textcoords="offset points", va="top", fontsize=6.5, color=color, zorder=4)
            for p in pts:
                ax.plot([p["cells"]], [max(p["secs"], 0.1)], linestyle="none", markersize=5.5, zorder=3,
                        **marker(p, color, th))
    format_axes(ax, th, max(limits.values(), default=1000) * 2.5)
    legend(fig, th)
    fig.suptitle("Frontier, all axes: time to verdict by design size", x=0.01, ha="left", fontsize=12,
                 fontweight="bold", y=1 - 0.1 / fig.get_figheight())
    fig.text(0.99, 1 - 0.75 / fig.get_figheight(), "hollow marks sit at their axis' time limit (30 to 900 s)",
             ha="right", fontsize=7.5, color=th["ink2"])
    fig.savefig(out / "frontier_all.png", dpi=160)
    return out / "frontier_all.png"


def draw(panels, data, limits, engines, th, out):
    ncol = 2 if len(panels) > 1 else 1
    nrow = math.ceil(len(panels) / ncol)
    fig, axes = plt.subplots(nrow, ncol, figsize=(6.2 * ncol, 3.6 * nrow + 0.9), squeeze=False)
    fig.subplots_adjust(left=0.08, right=0.98, top=1 - 0.95 / (3.6 * nrow + 0.9), bottom=0.07, hspace=0.45,
                        wspace=0.18)
    table = []
    for ax, key in zip(axes.flat, panels):
        limit = limits.get(key)
        for j, (kind, name) in enumerate(TOOLS):
            pts = sorted(data[kind].get(key, []), key=lambda p: p["cells"])
            color = th["series"][j]
            ok = [p for p in pts if p["result"] == "PASS"]
            if ok:
                ax.plot([p["cells"] for p in ok], [max(p["secs"], 0.1) for p in ok], color=color, lw=1.6, zorder=2)
            for p in pts:
                ax.plot([p["cells"]], [max(p["secs"], 0.1)], linestyle="none", markersize=6, zorder=3,
                        **marker(p, color, th))
                table.append({"bench": key[0], "axis": key[1], "tool": name, "cells": p["cells"], "run": p["run"],
                              "result": p["result"], "secs": round(p["secs"], 1),
                              "engine": engines.get(key) if kind == "plain" else ""})
        if limit:
            ax.axhline(limit, color=th["muted"], lw=1, ls="--", zorder=1)
            ax.text(0.01, limit, f" limit {limit:,.0f} s", transform=ax.get_yaxis_transform(), va="bottom",
                    fontsize=7.5, color=th["ink2"])
        format_axes(ax, th, (limit or 1000) * 2.5)
        ax.set_title(f"{key[0].removeprefix('ol_')}: {key[1]}", loc="left", fontsize=10, fontweight="bold",
                     color=th["ink"])
    for ax in list(axes.flat)[len(panels):]:
        ax.axis("off")
    legend(fig, th)
    fig.suptitle("Frontier: time to verdict by design size", x=0.01, ha="left", fontsize=12, fontweight="bold",
                 y=1 - 0.1 / fig.get_figheight())
    fig.savefig(out / "frontier.png", dpi=160)
    write_csv(out / "frontier.csv", table)
    return out / "frontier.png"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seq", default="frontier_focused", help="frontier.py tag of seq_prove")
    ap.add_argument("--eqy", default="frontier_focused_eqy", help="frontier.py tag of eqy")
    ap.add_argument("--out", type=Path, default=RUNS / "compare")
    ap.add_argument("--theme", choices=THEMES, default="light")
    args = ap.parse_args()
    seq, limits = frontier_points(args.seq, want_eqy=False)
    eqy, eqy_limits = frontier_points(args.eqy, want_eqy=True)
    limits.update(eqy_limits)
    panels = list(dict.fromkeys([*seq, *eqy]))
    plain = {k: plain_points(*k) for k in panels}
    data = {"seq": seq, "eqy": eqy, "plain": {k: pts for k, (_engine, pts) in plain.items()}}
    engines = {k: engine for k, (engine, _pts) in plain.items()}
    args.out.mkdir(parents=True, exist_ok=True)
    th = THEMES[args.theme]
    style(th)
    print(draw(panels, data, limits, engines, th, args.out))
    print(draw_combined(panels, data, limits, th, args.out))


if __name__ == "__main__":
    main()
