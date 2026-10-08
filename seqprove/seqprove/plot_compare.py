# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "matplotlib>=3.11.1",
# ]
# ///
"""Figures comparing the plain sby miter, eqy and seq_prove (Houdini k-induction) from run_bench results.

usage: uv run plot_compare.py [--out DIR] [--theme light|dark] [--no-build-time]
                              [--seq TAGS] [--plain TAGS] [--eqy TAGS]
                              [--seq-mut TAGS] [--plain-mut TAGS] [--eqy-mut TAGS]

Writes DIR/compare_times.png (time to verdict per design and tool) and DIR/compare_mutants.png (verdict
per mutant and tool), each with a CSV. TAGS: comma-separated run_bench tags under seqprove/runs/
(`TAG:Title` names a group); the later tag wins. Verdict: PASS/FAIL if a row decided it (disagreeing sby
engines -> ERROR), else UNKNOWN if a row timed out, else ERROR. seq_prove times include the model build
unless --no-build-time. VACUOUS: matched in seqprove/runs/overrides.csv (fnmatch on tool,bench,run,variant;
EXCLUDE drops a mutant). An eqy FAIL on internal matched nets only is plotted as FAIL; the CSV's `how` says so.
"""
import argparse
import csv
import fnmatch
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter
from matplotlib.transforms import blended_transform_factory

RUNS = Path(__file__).resolve().parent.parent / "runs"

# tools in the order of the categorical color slots
TOOLS = [("seq", "seq_prove (Houdini)"), ("plain", "plain sby miter"), ("eqy", "eqy")]
THEMES = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781", "grid": "#e1e0d9",
                  "axis": "#c3c2b7", "unknown": "#f0efec", "series": ["#2a78d6", "#eb6834", "#1baf7a"]},
    "dark": {"surface": "#1a1a19", "ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781", "grid": "#2c2c2a",
                 "axis": "#383835", "unknown": "#383835", "series": ["#3987e5", "#d95926", "#199e70"]},
}
VERDICTS = ["PASS", "FAIL", "VACUOUS", "UNKNOWN", "ERROR"]
VERDICT_TEXT = {"PASS": "PASS", "FAIL": "FAIL", "VACUOUS": "PASS, vacuous",
                "UNKNOWN": "UNKNOWN (no verdict at the limit)", "ERROR": "ERROR"}
LETTER = {"PASS": "P", "FAIL": "F", "VACUOUS": "V", "UNKNOWN": "?", "ERROR": "E"}

# left out of the time figure because a larger instance of the same design is in it
DEFAULT_SKIP = "ol_dyn_sft/W1152_M4_T30"

DEFAULT = {
    "seq": "ab_auto:A/B set,wide_boolector,hard_auto:hard set,long_auto:long run,neorv32:IP cores,compare_internal",
    "plain": "ab_plain,hard_plain,long_plain,neorv32,compare_internal,compare_internal_sha256fix",
    "eqy": "eqy_ab,eqy_hard,eqy_long,neorv32,compare_internal",
    "seq_mut": "mut_final,hard_mut,neorv32_mut",
    "plain_mut": "mut_auto,mut_auto2,hard_mut,neorv32_mut",
    "eqy_mut": "eqy_mut,eqy_hard_mut,neorv32_mut",
}


def is_tool(kind, tool):
    return {"seq": tool == "seq_prove", "eqy": tool == "eqy", "plain": tool.startswith("sby:")}[kind]


def parse_tags(spec):
    out = []
    for t in spec.split(","):
        tag, _, title = t.partition(":")
        out.append((tag.strip(), title.strip() or None))
    return out


def load(tag):
    f = RUNS / tag / "results.csv"
    if not f.exists():
        print(f"warning: {f} not found, skipped")
        return []
    with open(f) as fh:
        return list(csv.DictReader(fh))


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def aggregate(rows, build_time):
    """One verdict from the rows of one tool, case and tag (one row per sby engine)."""
    def secs(r):
        return num(r["wall_secs"]) + (num(r.get("build_secs")) if build_time and r["tool"] == "seq_prove" else 0)
    decided = [r for r in rows if r["result"] in ("PASS", "FAIL")]
    if decided:
        if len({r["result"] for r in decided}) > 1:
            return {"result": "ERROR", "secs": max(map(secs, rows)), "how": "engines disagree", "row": decided[0]}
        best = min(decided, key=secs)
        return {"result": best["result"], "secs": secs(best), "how": best["tool"], "row": best}
    res = "UNKNOWN" if any(r["result"] == "UNKNOWN" for r in rows) else "ERROR"
    worst = max(rows, key=secs)
    return {"result": res, "secs": secs(worst), "how": worst["reason"], "row": worst}


def collect(kind, tags, key_fn, build_time):
    """{key: verdict} for one tool over its tags (the later tag wins), {key: first tag} and build errors."""
    out, first, build_err = {}, {}, set()
    for tag, _ in tags:
        groups = defaultdict(list)
        for r in load(tag):
            if r["tool"] == "build" and r["result"] == "ERROR":
                build_err.add(key_fn(r))
            elif is_tool(kind, r["tool"]):
                groups[key_fn(r)].append(r)
        for k, rows in groups.items():
            if kind != "plain":
                rows = rows[-1:]          # a repeated row: the last run counts
            out[k] = aggregate(rows, build_time) | {"tag": tag}
            first.setdefault(k, tag)
    return out, first, build_err


def apply_overrides(kind, data, overrides):
    for v in data.values():
        r = v["row"]
        for o in overrides:
            if fnmatch.fnmatch(kind, o["tool"]) and all(fnmatch.fnmatch(r[f], o[f]) for f in ("bench", "run", "variant")):
                v["result"], v["how"] = o["result"], o["reason"]


def vcd_final(path):
    """Final value of every variable in a VCD, i.e. the failing step of a pdr trace."""
    ids, scope, vals = {}, [], {}
    with open(path) as fh:
        lines = fh.read().split("\n")
    for ln in lines:
        tok = ln.split()
        if not tok:
            continue
        if tok[0] == "$scope":
            scope.append(tok[2])
        elif tok[0] == "$upscope":
            scope.pop()
        elif tok[0] == "$var":
            ids.setdefault(tok[3], []).append(".".join(scope[1:] + [tok[4]]))
        elif tok[0][0] in "bB" and len(tok) == 2:
            for n in ids.get(tok[1], []):
                vals[n] = tok[0][1:]
        elif tok[0][0] in "01xz":
            for n in ids.get(tok[0][1:], []):
                vals[n] = tok[0][0]
    return vals


def base_name(n):
    return re.sub(r"\[\d+\]$", "", re.sub(r"<([^<>]*)>", r"[\1]", n))   # VCD writes [x] as <x>


def refine_eqy_fail(v):
    """Note in `how` when eqy's pdr traces only fail on internal nets, not on a gold output port."""
    r = v["row"]
    wd = RUNS / v["tag"] / r["bench"] / r["run"] / r["variant"] / "eqy"
    traces = list(wd.glob("strategies/*/pdr/*/engine_*/trace*.vcd"))
    if v["result"] != "FAIL" or not traces or not (wd / "gold.ids").exists():
        return
    ports = {base_name(ln.split()[1]) for ln in (wd / "gold.ids").read_text().split("\n")
             if ln.startswith("top ") and "P=O" in ln.split()}
    failing = set()
    for t in traces:
        for n, x in vcd_final(t).items():
            m = re.search(r"__po_(.+)__assert\.okay$", n)
            if m and x == "0":
                failing.add(base_name(m.group(1)))
    if failing and not failing & ports:
        v["how"] = "internal nets only: " + ", ".join(sorted(failing)[:3])


def short_label(bench, run):
    b = bench.removeprefix("ol_")
    r = re.sub(r"_T\d+$", "", run).removeprefix("orfs_")
    if len(r) > 12:
        r = "_".join(t for t in r.split("_") if re.match(r"W\d+$", t)) or r[:12]
    return f"{b} {r}"


def tint(hex_color, surface, a):
    """hex_color mixed with the surface color, a=1 is hex_color."""
    c = [int(hex_color[i:i + 2], 16) for i in (1, 3, 5)]
    s = [int(surface[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(a * x + (1 - a) * y):02x}" for x, y in zip(c, s))


def ink_on(hex_color):
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return "#0b0b0b" if 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.5 else "#ffffff"


def style(th):
    plt.rcParams.update({"font.family": "sans-serif", "font.size": 9, "text.color": th["ink"],
                         "axes.labelcolor": th["ink2"], "xtick.color": th["muted"], "ytick.color": th["ink"],
                         "axes.edgecolor": th["axis"], "figure.facecolor": th["surface"],
                         "axes.facecolor": th["surface"], "savefig.facecolor": th["surface"]})


def marker(v, color, th):
    res = v["result"]
    hollow = {"markerfacecolor": th["surface"], "markeredgecolor": color, "markeredgewidth": 1.6}
    filled = {"markerfacecolor": color, "markeredgecolor": th["surface"], "markeredgewidth": 1.2}
    return {"PASS": dict(marker="o", **filled), "FAIL": dict(marker="X", **filled),
            "VACUOUS": dict(marker="D", **hollow),
            "UNKNOWN": dict(marker=">", **hollow), "ERROR": dict(marker="s", **hollow)}[res]


MARK_DEC = 0.075     # marker width in decades of the time axis: closer marks are nudged apart
LABEL_DEC = 0.3      # width of a time label in decades: closer labels go to the other side


def fmt_secs(s):
    return f"{s:.1f} s" if s < 10 else f"{s:,.0f} s"


def draw_row(ax, y, marks, xmin, th):
    """The marks of one design on one line, each with its time above or below it, or to the right if both
    are taken. Marks closer than a marker width are moved right; the label keeps the measured time."""
    last_x, last_label = None, {-1: None, 1: None}      # side: -1 above, 1 below
    for j, v in sorted(marks, key=lambda m: m[1]["secs"]):
        lx = math.log10(max(v["secs"], xmin))
        if last_x is not None:
            lx = max(lx, last_x + MARK_DEC)
        last_x = lx
        side = next((s for s in (-1, 1) if last_label[s] is None or lx - last_label[s] >= LABEL_DEC), 0)
        ax.plot([10 ** lx], [y], linestyle="none", markersize=8, zorder=3, **marker(v, th["series"][j], th))
        if side:
            last_label[side] = lx
            ax.text(10 ** lx, y + side * 0.33, fmt_secs(v["secs"]), ha="center", va="center", fontsize=6.5,
                    color=th["ink2"], zorder=4)
        else:
            ax.text(10 ** (lx + MARK_DEC * 0.8), y, fmt_secs(v["secs"]), ha="left", va="center", fontsize=6.5,
                    color=th["ink2"], zorder=4)


def plot_times(args, th, out):
    seq_tags = parse_tags(args.seq)
    data = {}
    first = {}
    for kind, spec in (("seq", args.seq), ("plain", args.plain), ("eqy", args.eqy)):
        d, f, _ = collect(kind, parse_tags(spec), lambda r: (r["bench"], r["run"]), args.build_time)
        apply_overrides(kind, d, args.overrides)
        if kind == "eqy":
            for v in d.values():
                refine_eqy_fail(v)
        data[kind] = d
        if kind == "seq":
            first = f
    titles, title = {}, None
    for tag, t in seq_tags:
        title = t or title or tag
        titles[tag] = title
    groups = defaultdict(list)
    for k in data["seq"]:
        if not any(fnmatch.fnmatch(f"{k[0]}/{k[1]}", p) for p in args.skip):
            groups[titles[first[k]]].append(k)

    rows, y, ys, heads = [], 0.0, {}, []
    for g, keys in groups.items():
        heads.append((g, y))
        y += 0.9
        for k in keys:
            ys[k] = y
            rows.append(k)
            y += 1.0
        y += 0.4
    top_in, bottom_in = 1.05, 0.85
    height = top_in + bottom_in + 0.33 * y
    fig, ax = plt.subplots(figsize=(10, height))
    fig.subplots_adjust(left=0.2, right=0.97, top=1 - top_in / height, bottom=bottom_in / height)
    xmin, xmax = 0.8, 2e4
    for g, gy in heads:
        ax.text(0.01, gy + 0.35, g, transform=blended_transform_factory(fig.transFigure, ax.transData),
                ha="left", va="center",
                fontsize=9, fontweight="bold", color=th["ink"], clip_on=False)
        if gy > 0:
            ax.axhline(gy - 0.2, color=th["grid"], lw=1)
    for k in rows:
        ax.axhline(ys[k], color=th["grid"], lw=0.7, zorder=1)
        draw_row(ax, ys[k], [(j, data[kind][k]) for j, (kind, _) in enumerate(TOOLS) if k in data[kind]], xmin, th)
    table = [{"bench": k[0], "run": k[1], "tool": name, "result": v["result"], "secs": round(v["secs"], 1),
              "tag": v["tag"], "how": v["how"]}
             for kind, name in TOOLS for k in rows if (v := data[kind].get(k))]
    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f} s"))
    ax.set_xlim(xmin, xmax)
    ax.set_ylim(y, -0.2)
    ax.set_yticks([ys[k] for k in rows], [short_label(*k) for k in rows])
    ax.tick_params(axis="y", length=0)
    ax.tick_params(axis="x", colors=th["muted"])
    ax.grid(axis="x", which="major", color=th["grid"], lw=1)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.set_xlabel("time to verdict, seconds (log scale)" + (", seq_prove incl. model build" if args.build_time else ""))
    fig.suptitle("Equivalence of the original designs: time to verdict", x=0.01, ha="left", fontsize=12,
                 fontweight="bold", y=1 - 0.12 / height)
    tool_h = [Line2D([], [], linestyle="none", marker="o", markersize=8, markerfacecolor=th["series"][j],
                     markeredgecolor=th["surface"], label=n) for j, (_, n) in enumerate(TOOLS)]
    gray = th["ink2"]
    ver_h = [Line2D([], [], linestyle="none", markersize=8, label=VERDICT_TEXT[r],
                    **marker({"result": r}, gray, th)) for r in VERDICTS]
    leg = ax.legend(handles=tool_h + ver_h, ncol=4, loc="lower left", bbox_to_anchor=(-0.25, 1.0), frameon=False,
                    fontsize=8, handletextpad=0.4, columnspacing=1.2)
    for t in leg.get_texts():
        t.set_color(th["ink"])
    fig.savefig(out / "compare_times.png", dpi=160)
    write_csv(out / "compare_times.csv", table)
    return out / "compare_times.png"


def plot_mutants(args, th, out):
    data, order, build_err = {}, [], set()
    for kind, spec in (("seq", args.seq_mut), ("plain", args.plain_mut), ("eqy", args.eqy_mut)):
        d, f, be = collect(kind, parse_tags(spec), lambda r: (r["bench"], r["run"], r["variant"]), False)
        apply_overrides(kind, d, args.overrides)
        if kind == "eqy":
            for v in d.values():
                refine_eqy_fail(v)
        data[kind] = d
        build_err |= be
        order += [k for k in f if k not in order]
    originals = {"new", "old"}
    excluded = {k for d in data.values() for k, v in d.items() if v["result"] == "EXCLUDE"}
    muts = [k for k in order if k[2] not in originals and k not in build_err and k not in excluded]
    groups = defaultdict(list)
    for k in muts:
        groups[(k[0], k[1])].append(k)

    tile, gap, ggap = 1.0, 0.14, 1.2
    xs, x, gx = {}, 0.0, []
    for g, keys in groups.items():
        gx.append((g, x, x + len(keys) * tile))
        for k in keys:
            xs[k] = x
            x += tile
        x += ggap
    top_in, axes_in, bottom_in = 1.2, 3 * 0.32, 0.6
    width, height = 2.4 + 0.2 * x + 1.9, top_in + axes_in + bottom_in
    fig = plt.figure(figsize=(width, height))
    ax = fig.add_axes([2.4 / width, bottom_in / height, 0.2 * x / width, axes_in / height])
    table, counts = [], {}
    for j, (kind, name) in enumerate(TOOLS):
        color = th["series"][j]
        yy = j * tile
        c = Counter()
        for k in muts:
            v = data[kind].get(k)
            res = v["result"] if v else None
            c[res or "not run"] += 1
            fill, hatch, letter, lc = th["surface"], None, "–", th["muted"]
            if res == "FAIL":
                fill, letter = color, "F"
                lc = ink_on(color)
            elif res == "PASS":
                fill, letter, lc = tint(color, th["surface"], 0.35), LETTER[res], th["ink"]
            elif res == "VACUOUS":
                fill, hatch, letter, lc = th["surface"], "////", "V", th["ink"]
            elif res == "UNKNOWN":
                fill, letter, lc = th["unknown"], "?", th["ink2"]
            elif res == "ERROR":
                fill, letter, lc = th["ink2"], "E", th["surface"]
            ax.add_patch(Rectangle((xs[k] + gap / 2, yy + gap / 2), tile - gap, tile - gap, facecolor=fill,
                                   edgecolor=color if hatch else (th["grid"] if res is None else "none"),
                                   hatch=hatch, lw=0.8 if (hatch or res is None) else 0))
            ax.text(xs[k] + tile / 2, yy + tile / 2, letter, ha="center", va="center", fontsize=6.5, color=lc)
            if v:
                table.append({"bench": k[0], "run": k[1], "variant": k[2], "tool": name, "result": res,
                                  "secs": round(v["secs"], 1), "tag": v["tag"], "how": v["how"]})
        counts[kind] = c
        summary = "  ".join(f"{LETTER.get(r, r)} {c[r]}" for r in VERDICTS + ["not run"] if c[r])
        ax.text(x - ggap + 0.6, yy + tile / 2, summary, ha="left", va="center", fontsize=8, color=th["ink"])
        ax.text(-1.0, yy + tile / 2, name, ha="right", va="center", fontsize=9, color=th["ink"])
        ax.plot([-0.5], [yy + tile / 2], marker="o", markersize=7, color=color, clip_on=False)
    for (b, r), x0, x1 in gx:
        ax.text((x0 + x1) / 2, -0.35, short_label(b, r), ha="center", va="bottom", fontsize=8, color=th["ink"])
    for k in muts:
        ax.text(xs[k] + tile / 2, 3 * tile + 0.15, k[2], ha="center", va="top", rotation=90, fontsize=6,
                color=th["muted"])
    ax.set_xlim(0, x - ggap)
    ax.set_ylim(3 * tile, 0)
    ax.axis("off")
    fig.text(0.01, 1 - 0.15 / height, "Mutants: verdict per tool", fontsize=12, fontweight="bold", va="top")
    fig.text(0.01, 1 - 0.5 / height, "P = PASS (light tile), F = FAIL (solid), V = vacuous "
             "PASS (hatched), ? = UNKNOWN, E = ERROR, – = not run", fontsize=8, color=th["ink2"], va="top")
    fig.savefig(out / "compare_mutants.png", dpi=160)
    write_csv(out / "compare_mutants.csv", table)
    return out / "compare_mutants.png"


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=RUNS / "compare", help="output directory")
    ap.add_argument("--theme", choices=THEMES, default="light")
    ap.add_argument("--no-build-time", dest="build_time", action="store_false",
                    help="seq_prove time without its model build")
    ap.add_argument("--overrides", type=Path, default=RUNS / "overrides.csv")
    ap.add_argument("--skip", default=DEFAULT_SKIP,
                    help=f"comma-separated BENCH/RUN patterns left out of the time figure (default {DEFAULT_SKIP})")
    for key, spec in DEFAULT.items():
        ap.add_argument("--" + key.replace("_", "-"), default=spec, help=f"tags (default {spec})")
    args = ap.parse_args()
    args.skip = [p for p in args.skip.split(",") if p]
    args.overrides = (list(csv.DictReader(args.overrides.read_text().splitlines()))
                      if args.overrides.exists() else [])
    args.out.mkdir(parents=True, exist_ok=True)
    th = THEMES[args.theme]
    style(th)
    for p in (plot_times(args, th, args.out), plot_mutants(args, th, args.out)):
        print(p)


if __name__ == "__main__":
    main()
