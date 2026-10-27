import ast
import itertools
import tomllib
from pathlib import Path

DESIGNS = Path(__file__).resolve().parent / "designs"
FRONTENDS = ("ghdl", "slang")
NOT_YET = ("settle", "valid_guard")
FLAVORS = ("yosys", "orfs")
FLOW_KEYS = {"yosys": {"enabled"}, "orfs": {"enabled", "config"}}
KEYS = {
    "top",
    "exercises",
    "source",
    "params",
    "points",
    "ladders",
    "clocks",
    "resets",
    "compare",
    "cover",
    "power_up",
    "flows",
    "limits",
}
COVER_ENGINES = ("smtbmc yices", "smtbmc boolector", "smtbmc bitwuzla", "smtbmc z3")
REQUIRE_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.USub,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Name,
    ast.Load,
    ast.Constant,
)


class DesignError(ValueError):
    pass


def load(path):
    path = Path(path).resolve()
    d = tomllib.loads(path.read_text())

    def err(msg):
        return DesignError(f"{path}: {msg}")

    if unknown := sorted(set(d) - KEYS):
        raise err(f"unknown keys {unknown}")
    d["name"] = (
        path.parent.relative_to(DESIGNS).as_posix()
        if path.parent.is_relative_to(DESIGNS)
        else path.parent.name
    )
    d["dir"] = path.parent
    if "top" not in d:
        raise err("`top` is required")
    src = d.setdefault("source", {})
    if src.get("frontend") not in FRONTENDS:
        raise err(
            f"[source] frontend must be one of {FRONTENDS}, not {src.get('frontend')!r}"
        )
    if ("files" in src) == ("flist" in src):
        raise err("[source] needs exactly one of `files` and `flist`")
    for k, v in (("args", []), ("defines", {}), ("env", {})):
        src.setdefault(k, v)
    if "generate" in src and (
        not isinstance(src["generate"], list) or not src["generate"]
    ):
        raise err("[source] generate must be a non-empty list (the command)")
    src["env"] = {
        k: v.replace("{design}", str(d["dir"])) for k, v in src["env"].items()
    }
    src["args"] = [a.replace("{design}", str(d["dir"])) for a in src["args"]]
    d.setdefault("params", {})
    for name, p in d["params"].items():
        if not p.get("values"):
            raise err(f"[params.{name}] needs a non-empty `values`")
    pts = d.setdefault("points", {})
    if set(pts) - {"require"}:
        raise err(f"[points] unknown {sorted(set(pts) - {'require'})}")
    if "require" in pts:
        try:
            tree = ast.parse(pts["require"], mode="eval")
        except SyntaxError as e:
            raise err(f"[points] require: {e}") from None
        bad = sorted(
            {
                type(n).__name__
                for n in ast.walk(tree)
                if not isinstance(n, REQUIRE_NODES)
            }
        )
        names = sorted(
            {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - set(d["params"])
        )
        if bad or names:
            raise err(f"[points] require: not allowed: {bad + names}")
        try:
            if not points(d):
                raise err("[points] require drops every point")
        except ArithmeticError as e:
            raise err(f"[points] require: {e}") from None
    d.setdefault("clocks", [])
    for c in d["clocks"]:
        c.setdefault("edge", "posedge")
        c.setdefault("period_ns", 10)
        if c["edge"] not in ("posedge", "negedge") or not c["period_ns"] > 0:
            raise err(
                f"clock {c.get('name')}: edge must be posedge or negedge, period_ns > 0"
            )
    clocks = {c["name"]: c for c in d["clocks"]}
    d.setdefault("resets", [])
    for r in d["resets"]:
        r.setdefault("hold", 2)
        if (
            r.get("clock") not in clocks
            or r.get("active") not in (0, 1)
            or r["hold"] < 1
        ):
            raise err(
                f"reset {r.get('name')}: needs a declared `clock`, `active` 0 or 1 and `hold` >= 1"
            )
    cmp = d.setdefault("compare", {})
    for k in NOT_YET:
        if k in cmp:
            raise err(f"[compare] {k} is not implemented by the miter generator yet")
    for e in cmp.setdefault("exclude", []):
        if not e.get("port") or not real_why(e):
            raise err(f"[compare] exclude {e}: needs `port` and a real `why`")
    cov = d.setdefault("cover", {})
    cov.setdefault("depth", 64)
    cov.setdefault("engine", "smtbmc yices")
    if (
        set(cov) - {"depth", "engine"}
        or type(cov["depth"]) is not int
        or cov["depth"] < 1
        or cov["engine"] not in COVER_ENGINES
    ):
        raise err(
            f"[cover] {cov}: only `depth` (steps, >= 1) and `engine` (one of {COVER_ENGINES})"
        )
    pu = d.setdefault("power_up", {})
    pu.setdefault("gate", "free")
    if pu["gate"] not in ("free", "rtl_init") or (
        pu["gate"] == "rtl_init" and not real_why(pu)
    ):
        raise err(
            f"[power_up] {pu}: gate must be `free` or `rtl_init`, and `rtl_init` needs a real `why`"
        )
    fl = d.setdefault("flows", {})
    if unknown := sorted(set(fl) - set(FLAVORS)) or sorted(
        f"{f}.{k}" for f in fl for k in set(fl[f]) - FLOW_KEYS[f]
    ):
        raise err(f"[flows] unknown {unknown}")
    for f in FLAVORS:
        fl.setdefault(f, {}).setdefault("enabled", True)
    fl["orfs"].setdefault("config", [])
    lim = d.setdefault("limits", {})
    lim.setdefault("timeout", 300)
    lim.setdefault("build_timeout", 3600)
    names = set()
    for lad in d.setdefault("ladders", []):
        if (
            set(lad) - {"name", "points", "timeout"}
            or not lad.get("name")
            or lad["name"] in names
        ):
            raise err(
                f"[[ladders]] {lad.get('name')!r}: needs a unique `name`, `points` and optional `timeout` only"
            )
        names.add(lad["name"])
        if not lad.get("points") or not all(
            isinstance(q, dict) and q for q in lad["points"]
        ):
            raise err(
                f"[[ladders]] {lad['name']}: `points` must be a non-empty list of parameter tables"
            )
        lad.setdefault("timeout", lim["timeout"])
    return d


def real_why(entry):
    why = str(entry.get("why", "")).strip()
    return bool(why) and why.upper() != "TODO"


def points(d):
    if "generate" in d["source"] and not d["params"]:
        return []
    names = sorted(d["params"])
    cross = [
        dict(zip(names, vals))
        for vals in itertools.product(*(d["params"][n]["values"] for n in names))
    ]
    req = d["points"].get("require")
    code = (
        compile(ast.parse(req, mode="eval"), "[points] require", "eval")
        if req
        else None
    )
    return [
        p for p in cross if code is None or eval(code, {"__builtins__": {}}, dict(p))
    ]


def point_name(point):
    return ",".join(f"{k}={v}" for k, v in sorted(point.items())) or "default"
