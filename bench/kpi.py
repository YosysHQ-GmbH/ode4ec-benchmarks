import csv
import os
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
KPI_FIELDS = [
    "experiment",
    "check",
    "tools",
    "versions",
    "set",
    "group",
    "instances",
    "solved",
    "S",
    "gate",
]
INSTANCE = (
    "design",
    "axis",
    "point",
    "flavor",
    "variant",
    "tools",
    "versions",
    "limit",
)
SCORED = ("eqy", "sby_mi")


def where(r):
    return r["design"], r.get("axis", ""), r["point"], r["flavor"]


def s_of(row, covered, confirmed):
    if row["check"] not in SCORED or row["variant"] != "orig":
        return ""
    solved = (row["result"] == "PASS" and row["input_hash"] in covered) or (
        row["result"] == "FAIL"
        and (row["check"] == "sby_mi" or row["input_hash"] in confirmed)
    )
    t, limit = float(row["secs"] or 0), float(row["limit"])
    return round(t / limit, 4) if solved and t <= limit else 2.0


def update(results, fields):
    with open(results, newline="") as fh:
        rows = list(csv.DictReader(fh))
    covered = {
        r["input_hash"]
        for r in rows
        if r["check"] == "cover" and r["result"] == "COVERED"
    }
    confirmed = {
        r["input_hash"]
        for r in rows
        if r["check"] == "sby_mi" and r["result"] == "FAIL"
    }
    last = {}
    for r in rows:
        r["s"] = s_of(r, covered, confirmed)
        last[(r["check"], r.get("engine", ""), *(r.get(k, "") for k in INSTANCE))] = r
    tmp = f"{results}.tmp"
    with open(tmp, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows({k: r.get(k, "") for k in fields} for r in rows)
    os.replace(tmp, results)

    def group(r):
        if r.get("axis"):
            return "scaling", f"{r['design']} {r['axis']} {r['flavor']}"
        return "time-to-solve", r["design"].split("/")[0]

    inst = defaultdict(lambda: 2.0)
    for r in last.values():
        if r["s"] != "":
            k = (
                r["check"],
                r["tools"],
                r["versions"],
                *group(r),
                *(r.get(x, "") for x in INSTANCE),
            )
            inst[k] = min(inst[k], float(r["s"]))
    groups = defaultdict(list)
    for (check, tools, versions, set_, g, *_), s in inst.items():
        groups[(check, tools, versions, set_, g)].append(s)
    sby = [r for r in rows if r["check"] == "sby_mi"]
    orig_pass = {
        where(r) for r in sby if r["variant"] == "orig" and r["result"] == "PASS"
    }
    known = {
        r["input_hash"]
        for r in sby
        if r["variant"] != "orig" and r["result"] == "FAIL" and where(r) in orig_pass
    }
    mpass = defaultdict(lambda: (set(), set()))
    passes, caught = (
        defaultdict(set),
        defaultdict(set),
    )
    sby_fail = {
        where(r) for r in sby if r["variant"] == "orig" and r["result"] == "FAIL"
    }
    for r in last.values():
        k, at = (r["check"], r["tools"], r["versions"]), where(r)
        if r["check"] not in SCORED:
            continue
        if r["variant"] == "orig" and r["result"] == "PASS":
            passes[k].add(at)
        elif (
            r["variant"] != "orig"
            and r["result"] == "FAIL"
            and r["input_hash"] in known
        ):
            caught[k].add(at)
        elif r["variant"] != "orig" and r["result"] == "PASS":
            label = " ".join(x for x in (*at, r["variant"]) if x)
            mpass[k][r["input_hash"] not in known].add(label)

    def gate(k):
        bad, maybe = mpass[k]
        unverified = passes[k] - caught[k]
        disagree = sorted(passes[k] & sby_fail) if k[0] != "sby_mi" else []
        parts = [
            f"VOID: PASS on known-different mutants: {', '.join(sorted(bad))}"
            if bad
            else "ok"
        ]
        if unverified:
            parts.append(
                f"{len(unverified)}/{len(passes[k])} PASS points unverified "
                "(no FAIL on a known-different mutant)"
            )
        if disagree:
            shown = ", ".join(" ".join(x for x in at if x) for at in disagree[:5])
            more = " ..." if len(disagree) > 5 else ""
            parts.append(
                f"{len(disagree)} PASS points that sby_mi FAILs from reset: {shown}{more}"
            )
        if maybe:
            parts.append(
                f"PASS on mutants not known different (maybe equivalent): {', '.join(sorted(maybe))}"
            )
        return "; ".join(parts)

    out, sets = [], defaultdict(list)
    exp = Path(results).parent.name
    for (check, tools, versions, set_, g), ss in sorted(groups.items()):
        sg = sum(ss) / len(ss)
        sets[(check, tools, versions, set_)].append(sg)
        out.append(
            {
                "experiment": exp,
                "check": check,
                "tools": tools,
                "versions": versions,
                "set": set_,
                "group": g,
                "instances": len(ss),
                "solved": sum(x < 2 for x in ss),
                "S": round(sg, 4),
                "gate": gate((check, tools, versions)),
            }
        )
    for k in sorted({k[:3] for k in sets}):
        base = {
            "experiment": exp,
            "check": k[0],
            "tools": k[1],
            "versions": k[2],
            "gate": gate(k),
        }
        total = {}
        for set_, name in (("time-to-solve", "S_time"), ("scaling", "S_size")):
            n = [
                o
                for o in out
                if (o["check"], o["tools"], o["versions"], o["set"]) == (*k, set_)
            ]
            sgs = sets.get((*k, set_), [])
            total[name] = round(sum(sgs) / len(sgs), 4) if sgs else ""
            out.append(
                {
                    **base,
                    "set": set_,
                    "group": name,
                    "instances": sum(o["instances"] for o in n),
                    "solved": sum(o["solved"] for o in n),
                    "S": total[name],
                }
            )
        both = "" not in total.values()
        out.append(
            {
                **base,
                "set": "combined",
                "group": "S",
                "instances": "",
                "solved": "",
                "S": round((total["S_time"] + total["S_size"]) / 2, 4) if both else "",
            }
        )
    with open(Path(results).parent / "kpi.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=KPI_FIELDS)
        w.writeheader()
        w.writerows(out)
    return out


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    import run

    if len(sys.argv) != 2:
        sys.exit(__doc__)
    for r in update(HERE / "results" / sys.argv[1] / "results.csv", run.FIELDS):
        if r["group"].startswith("S"):
            print(
                f"{r['check']:7s} {r['tools']:10s} {r['group']:7s} {r['S']!s:7s} {r['solved']!s}/{r['instances']!s}"
                f"  gate {r['gate']}"
            )
