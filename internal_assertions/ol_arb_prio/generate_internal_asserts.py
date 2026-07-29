#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path

RUN_DIR = Path("run")

MODULE_RE = re.compile(r"^module \\(\S+)$")
CELL_RE = re.compile(r"^  cell \S+ \S+$")
CONNECT_RE = re.compile(r"^    connect \\(\S+) (.+)$")
WIRE_RE = re.compile(r"^  wire (.*)$")
WIRE_WIDTH_RE = re.compile(r"\bwidth (\d+)\b")
WIRE_OFFSET_RE = re.compile(r"\boffset (\d+)\b")
BIT_SUFFIX_RE = re.compile(r"^(.*)\[(\d+)\]$")
ATTR_SRC_RE = re.compile(r'^  attribute \\src "([^"]*)"$')

Wires = dict[str, tuple[int, int]]
RegCell = dict
Pair = tuple[str, "int | None", str]


def get_module_lines(rtlil_text: str, module: str) -> list[str]:
    lines = rtlil_text.splitlines()
    start = next(
        i
        for i, line in enumerate(lines)
        if (m := MODULE_RE.match(line)) and m.group(1) == module
    )
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "end")
    return lines[start + 1 : end]


def match_wire_widhts(token: str, wires: Wires) -> list[str]:
    if not token.startswith("\\") or "$" in token:
        return []
    name = token[1:]
    if "[" in name:
        return [name]
    width, offset = wires.get(name, (1, 0))
    if width <= 1:
        return [name]
    return [f"{name}[{offset + 1}]" for i in range(width)]


def parse_wires_and_ports(lines: list[str]) -> tuple[Wires, set[str]]:
    wires: Wires = {}
    ports: set[str] = set()

    for line in lines:
        m = WIRE_RE.match(line)
        if not m:
            continue
        declaration = m.group(1)
        name_token = declaration.split()[-1]
        if not name_token.startswith("\\"):
            continue
        width_match = WIRE_WIDTH_RE.search(declaration)
        offset_match = WIRE_OFFSET_RE.search(declaration)

        width = int(width_match.group(1)) if width_match else 1
        offset = int(offset_match.group(1)) if offset_match else 0

        wires[name_token[1:]] = (width, offset)

        if " input " in f" {declaration} " or " output " in f" {declaration} ":
            ports.add(name_token[1:])

    return wires, {b for name in ports for b in match_wire_widhts(f"\\{name}", wires)}


def parse_base_and_bit(name: str) -> tuple[str, "int | None"]:
    m = BIT_SUFFIX_RE.match(name)
    if m:
        return m.group(1), int(m.group(2))
    return name, None


def parse_register_cells(lines: list[str]) -> list[RegCell]:
    cells: list[RegCell] = []
    pending: str | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        if match := ATTR_SRC_RE.match(line):
            pending = re.sub(r"^(\.\./)+", "", match.group(1))
            i += 1
            continue
        if CELL_RE.match(line):
            src, pending = pending, None
            j = i + 1
            has_clk = False
            q_conn = None
            while lines[j] != "  end":
                if match_re := CONNECT_RE.match(lines[j]):
                    port, conn = match_re.groups()
                    if port == "CLK":
                        has_clk = True
                    elif port == "Q":
                        q_conn = conn.strip()
                j += 1
            if has_clk and q_conn:
                tokens = q_conn[1:-1].split() if q_conn.startswith("{") else [q_conn]
                for token in tokens:
                    if token.startswith("\\") and "$" not in token:
                        name, bit = parse_base_and_bit(token[1:])
                        cells.append({"src": src, "name": name, "bit": bit})
            i = j + 1
            continue
        pending = None
        i += 1
    return cells


def names_from_cells(cells: list[RegCell], wires: Wires, ports: set[str]) -> set[str]:
    names: set[str] = set()
    for c in cells:
        token = f"\\{c['name']}" if c["bit"] is None else f"\\{c['name']}[{c['bit']}]"
        for name in match_wire_widhts(token, wires):
            if name not in ports:
                names.add(name)
    return names


def match_by_src(
    gold_cells: list[RegCell],
    gate_cells: list[RegCell],
    gold_wires: Wires,
    gold_ports: set[str],
    gate_ports: set[str],
    already_matched: set[str],
) -> list[Pair]:
    gold_by_src: dict[str, list[str]] = {}
    for c in gold_cells:
        if c["src"] is None or c["bit"] is not None:
            continue
        width, offset = gold_wires.get(c["name"], (1, 0))
        bits = (
            {c["name"]}
            if width <= 1
            else {f"{c['name']}[{offset + i}]" for i in range(width)}
        )
        if bits & already_matched or bits & gold_ports:
            continue
        gold_by_src.setdefault(c["src"], []).append(c["name"])

    gate_by_src: dict[str, list[tuple[str, int]]] = {}
    for c in gate_cells:
        if c["src"] is None:
            continue
        full = c["name"] if c["bit"] is None else f"{c['name']}[{c['bit']}]"
        if full in already_matched or full in gate_ports:
            continue
        gate_by_src.setdefault(c["src"], []).append((full, c["bit"] or 0))

    pairs: list[Pair] = []
    for src, gold_regs in gold_by_src.items():
        if len(gold_regs) != 1:
            continue
        gold_name = gold_regs[0]
        width, _offset = gold_wires.get(gold_name, (1, 0))
        gate_regs = sorted(gate_by_src.get(src, []), key=lambda x: x[1])
        if len(gate_regs) != width:
            continue
        for i, (gate_full, _bit) in enumerate(gate_regs):
            pairs.append((gold_name, None if width <= 1 else i, gate_full))
    return pairs


def glob_escape(s: str) -> str:
    return re.sub(r"([*?\[\]])", r"\\\1", s)


def safe_ident(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def write_output_files(
    pairs: list[Pair], out_paths: dict[str, Path], gold_wires: Wires
) -> None:
    gold_bases = sorted({p[0] for p in pairs})
    gate_exposed = sorted({p[2] for p in pairs})

    expose_lines = [""]
    expose_lines.append(
        "expose " + " ".join(f"gold_top/w:\\{glob_escape(b)}" for b in gold_bases)
    )
    expose_lines.append(
        "expose " + " ".join(f"gate_top/w:\\{glob_escape(n)}" for n in gate_exposed)
    )
    out_paths["expose"].write_text("\n".join(expose_lines) + "\n")

    decl_lines = [""]
    ports_a_lines = [""]
    ports_b_lines = [""]
    assert_lines = [""]

    for base in gold_bases:
        width, offset = gold_wires[base]
        safe = safe_ident(base)
        wire_a, wire_b = f"ihv_{safe}_a", f"ihv_{safe}_b"
        width_decl = "" if width <= 1 else f"[{width - 1}:0] "
        decl_lines.append(f"wire {width_decl}{wire_a};")
        decl_lines.append(f"wire {width_decl}{wire_b};")
        ports_a_lines.append(f"      , .\\{base} ({wire_a})")

    for base, local, gate_full in pairs:
        safe = safe_ident(base)
        wire_a, wire_b = f"ihv_{safe}_a", f"ihv_{safe}_b"
        if local is None:
            ports_b_lines.append(f"      , .\\{gate_full} ({wire_b})")
            assert_lines.append(f"      assert({wire_a} == {wire_b});")
        else:
            ports_b_lines.append(f"      , .\\{gate_full} ({wire_b}[{local}])")
            assert_lines.append(
                f"      assert({wire_a}[{local}] == {wire_b}[{local}]);"
            )

    out_paths["decls"].write_text("\n".join(decl_lines) + "\n")
    out_paths["ports_a"].write_text("\n".join(ports_a_lines) + "\n")
    out_paths["ports_b"].write_text("\n".join(ports_b_lines) + "\n")
    out_paths["asserts"].write_text("\n".join(assert_lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backend",
        required=True,
        choices=["yosys", "orfs"],
    )
    parser.add_argument(
        "--combo",
        required=True,
    )
    args = parser.parse_args()

    GOLD_NETLIST = RUN_DIR / f"check_{args.combo}_gold.il"
    GATE_NETLIST = RUN_DIR / f"check_{args.combo}_{args.backend}_gate.il"

    OUT_FOLDER = Path("internal_asserts")

    suffix = f"{args.combo}_{args.backend}"
    out_expose_ys = OUT_FOLDER / f"expose_{suffix}.ys"
    out_decls_vh = OUT_FOLDER / f"decls_{suffix}.vh"
    out_ports_a_vh = OUT_FOLDER / f"ports_a_{suffix}.vh"
    out_ports_b_vh = OUT_FOLDER / f"ports_b_{suffix}.vh"
    out_asserts_vh = OUT_FOLDER / f"asserts_{suffix}.vh"

    out_paths = {
        "expose": out_expose_ys,
        "decls": out_decls_vh,
        "ports_a": out_ports_a_vh,
        "ports_b": out_ports_b_vh,
        "asserts": out_asserts_vh,
    }

    if not GOLD_NETLIST.exists():
        sys.exit(f"{GOLD_NETLIST} not found")
    if not GATE_NETLIST.exists():
        sys.exit(f"{GATE_NETLIST} not found")

    gold_content = GOLD_NETLIST.read_text()
    gold_lines = get_module_lines(gold_content, "gold_top")
    gold_wires, gold_ports = parse_wires_and_ports(gold_lines)
    gold_cells = parse_register_cells(gold_lines)
    gold_names = names_from_cells(gold_cells, gold_wires, gold_ports)

    gate_content = GATE_NETLIST.read_text()
    gate_lines = get_module_lines(gate_content, "gate_top")
    gate_wires, gate_ports = parse_wires_and_ports(gate_lines)
    gate_cells = parse_register_cells(gate_lines)
    gate_names = names_from_cells(gate_cells, gate_wires, gate_ports)

    matched_names = gold_names & gate_names
    name_pairs: list[Pair] = []
    for name in matched_names:
        base, bit = parse_base_and_bit(name)
        width, offset = gold_wires[base]
        local = None if width <= 1 else (bit - offset)
        name_pairs.append((base, local, name))

    src_pairs = match_by_src(
        gold_cells, gate_cells, gold_wires, gold_ports, gate_ports, matched_names
    )

    all_pairs = sorted(
        name_pairs + src_pairs,
        key=lambda p: (p[0], -1 if p[1] is None else p[1], p[2]),
    )

    write_output_files(all_pairs, out_paths=out_paths, gold_wires=gold_wires)


if __name__ == "__main__":
    main()
