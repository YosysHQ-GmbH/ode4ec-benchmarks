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
SIG_CHUNK_RE = re.compile(r"(\\\S+)(?:\s+\[(\d+)(?::(\d+))?\])?|\S+")

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
    # a bracketed name is a bit select, unless it is a wire of its own
    # (memory_map names word registers "mem[78]", gate-level bits "mem[78][2]")
    if "[" in name and name not in wires:
        return [name]
    width, offset = wires.get(name, (1, 0))
    if width <= 1:
        return [name]
    return [f"{name}[{offset + i}]" for i in range(width)]


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


def upto_wires(lines: list[str]) -> set[str]:
    """Wires declared with ascending indices (`logic [0:3] x`, RTLIL `upto`)."""
    return {
        m.group(1).split()[-1][1:]
        for line in lines
        if (m := WIRE_RE.match(line)) and " upto " in f" {m.group(1)} "
    }


# RTLIL numbers the bits of a sigspec select (`\w [i]`) by position (0 = LSB), whatever the wire's offset
# and direction; names use the HDL index (`w[i]`, e.g. gate bit wires from splitnets). For `[3:5]` (upto,
# offset 3) position 0 is w[5].
def hdl_index(wires: Wires, upto: set[str], name: str, pos: int) -> int:
    width, offset = wires.get(name, (1, 0))
    return offset + (width - 1 - pos if name in upto else pos)


def bit_position(wires: Wires, upto: set[str], name: str, index: int) -> int:
    width, offset = wires.get(name, (1, 0))
    return offset + width - 1 - index if name in upto else index - offset


def parse_base_and_bit(name: str) -> tuple[str, "int | None"]:
    m = BIT_SUFFIX_RE.match(name)
    if m:
        return m.group(1), int(m.group(2))
    return name, None


def cell_ports(lines: list[str], start: int) -> tuple[dict[str, str], int]:
    """({port: connected signal}, index of the `end` line) of the cell whose header is lines[start]."""
    ports: dict[str, str] = {}
    j = start + 1
    while lines[j] != "  end":
        if m := CONNECT_RE.match(lines[j]):
            ports[m.group(1)] = m.group(2).strip()
        j += 1
    return ports, j


def q_bits(q_conn: str, src: "str | None", wires: Wires, upto: set[str]) -> list[RegCell]:
    """The named bits of a flip-flop's Q connection. RTLIL sigspec: `\\w`, `\\w [i]`, `\\w [hi:lo]`,
    constants, `{ ... }` of those."""
    cells: list[RegCell] = []
    for m in SIG_CHUNK_RE.finditer(q_conn):
        wire = m.group(1)
        if wire is None or "$" in wire:
            continue
        wire = wire[1:]
        if m.group(2) is None:  # whole wire ("x[5]" may be a gate-level bit wire)
            name, bit = parse_base_and_bit(wire)
            cells.append({"src": src, "name": name, "bit": bit})
            continue
        hi = int(m.group(2))
        lo = hi if m.group(3) is None else int(m.group(3))
        for b in range(min(lo, hi), max(lo, hi) + 1):
            cells.append(
                {"src": src, "name": wire, "bit": hdl_index(wires, upto, wire, b), "sel": True}
            )
    return cells


def parse_register_cells(lines: list[str], wires: Wires, upto: set[str]) -> list[RegCell]:
    """Flip-flop output bits: {"src", "name", "bit": HDL index or None for a whole wire, "sel"}."""
    cells: list[RegCell] = []
    pending: str | None = None  # the src attribute in front of the next cell
    i = 0
    while i < len(lines):
        if match := ATTR_SRC_RE.match(lines[i]):
            pending = re.sub(r"^(\.\./)+", "", match.group(1))
            i += 1
        elif CELL_RE.match(lines[i]):
            src, pending = pending, None
            ports, end = cell_ports(lines, i)
            if "CLK" in ports and ports.get("Q"):
                cells += q_bits(ports["Q"], src, wires, upto)
            i = end + 1
        else:
            pending = None
            i += 1
    return cells


def anonymous_registers(lines: list[str]) -> list[str]:
    """Flip-flop outputs that are whole internal ($-named) wires, e.g. `$abc$206$...` after abc."""
    out: list[str] = []
    for i, line in enumerate(lines):
        if CELL_RE.match(line):
            ports, _end = cell_ports(lines, i)
            q = ports.get("Q")
            if "CLK" in ports and q and q.startswith("$") and " " not in q:
                out.append(q)
    return sorted(set(out))


def names_from_cells(cells: list[RegCell], wires: Wires, ports: set[str]) -> set[str]:
    names: set[str] = set()
    for c in cells:
        if c["bit"] is None or (c.get("sel") and wires.get(c["name"], (0, 0))[0] == 1):
            token = f"\\{c['name']}"  # whole wire, or the one bit of a 1-bit wire
        else:
            token = f"\\{c['name']}[{c['bit']}]"
        for name in match_wire_widhts(token, wires):
            if name not in ports:
                names.add(name)
    return names


def gold_registers_by_src(
    gold_cells: list[RegCell], gold_wires: Wires, gold_ports: set[str], already_matched: set[str]
) -> dict[str, list[str]]:
    """{source location: whole gold register wires declared there}, without matched bits and ports."""
    by_src: dict[str, list[str]] = {}
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
        by_src.setdefault(c["src"], []).append(c["name"])
    return by_src


def gate_bits_by_src(
    gate_cells: list[RegCell], gate_ports: set[str], already_matched: set[str]
) -> dict[str, list[tuple[str, int]]]:
    """{source location: (gate register bit, its index)}, without matched bits and ports."""
    by_src: dict[str, list[tuple[str, int]]] = {}
    for c in gate_cells:
        if c["src"] is None:
            continue
        full = c["name"] if c["bit"] is None else f"{c['name']}[{c['bit']}]"
        if full in already_matched or full in gate_ports:
            continue
        by_src.setdefault(c["src"], []).append((full, c["bit"] or 0))
    return by_src


def match_by_src(
    gold_cells: list[RegCell],
    gate_cells: list[RegCell],
    gold_wires: Wires,
    gold_ports: set[str],
    gate_ports: set[str],
    already_matched: set[str],
    gold_upto: set[str] = frozenset(),
) -> list[Pair]:
    """Pairs for registers synthesis renamed: a source location with exactly one gold register and as many
    gate register bits as that register is wide."""
    gold_by_src = gold_registers_by_src(gold_cells, gold_wires, gold_ports, already_matched)
    gate_by_src = gate_bits_by_src(gate_cells, gate_ports, already_matched)

    pairs: list[Pair] = []
    for src, gold_regs in gold_by_src.items():
        if len(gold_regs) != 1:
            continue
        gold_name = gold_regs[0]
        width, offset = gold_wires.get(gold_name, (1, 0))
        gate_regs = sorted(gate_by_src.get(src, []), key=lambda x: x[1])
        if len(gate_regs) != width:
            continue
        # the i-th lowest gate index is gold index offset + i (same declaration, same direction)
        for i, (gate_full, _bit) in enumerate(gate_regs):
            local = bit_position(gold_wires, gold_upto, gold_name, offset + i)
            pairs.append((gold_name, None if width <= 1 else local, gate_full))
    return pairs


def select_pairs(all_pairs: list[Pair], max_asserts: "int | None") -> list[Pair]:
    if max_asserts is None:
        return all_pairs
    bases = sorted({p[0] for p in all_pairs})
    if len(bases) <= max_asserts:
        return all_pairs
    stride = len(bases) / max_asserts
    selected = {bases[int(i * stride)] for i in range(max_asserts)}
    return [p for p in all_pairs if p[0] in selected]


def fsm_state_registers(
    gold_names: set[str],
    gold_wires: Wires,
    gate_names: set[str],
    max_bits: int,
    paired_gate: set[str] = frozenset(),
    anonymous: list[str] = (),
) -> list[tuple[str, list[tuple[int, str]]]]:
    """Gold registers that synthesis re-encoded (yosys fsm_recode, one-hot by default): the gate has
    register bits of the same name beyond the gold width. Only gold widths up to max_bits, and at most
    2**width same-named gate bits (one per state).
    The gate side is those bits plus the orphan gate register bits (not in paired_gate) of the same
    scope or without a usable name: after fsm_map/abc some state flip-flops carry other net names
    (e.g. `state_d[1]`, `$abc$...`). Orphans get index -1."""
    gate_bits: dict[str, list[tuple[int, str]]] = {}
    for n in gate_names:
        b, j = parse_base_and_bit(n)
        if j is not None:
            gate_bits.setdefault(b, []).append((j, n))
    orphans = sorted(n for n in gate_names if n not in paired_gate) + list(anonymous)

    def scope(n: str) -> str:
        return parse_base_and_bit(n)[0].rpartition(".")[0]

    bases = set()
    for n in gold_names:
        b, _ = parse_base_and_bit(n)
        bases.add(b if b in gold_wires else n)
    out = []
    for b in sorted(bases):
        if b not in gold_wires or b not in gate_bits:
            continue
        width, offset = gold_wires[b]
        bits = sorted(gate_bits[b])
        if 1 < width <= max_bits and bits[-1][0] >= offset + width and len(bits) <= 2**width:
            own = {g for _, g in bits}
            extra = [
                (-1, g)
                for g in orphans
                if g not in own and (g.startswith("$") or scope(g) == scope(b))
            ]
            out.append((b, bits + extra))
    return out


def recoded_state_registers(
    gold_names: set[str], gold_wires: Wires, gate_names: set[str], max_bits: int
) -> list[tuple[str, list[tuple[int, str]]]]:
    """Gold registers of 2..max_bits bits (every bit a register) of which the gate keeps fewer, but at
    least two, register bits of the same name and none beyond the gold width (that case is
    fsm_state_registers). Either a state register re-encoded into fewer flip-flops (yosys fsm_opt drops
    the unused codes before fsm_recode: 3 used states in a 4-bit register become 3 one-hot bits), or a
    register that lost constant bits. Not told apart here: the candidates are guesses either way."""
    gold_bits: dict[str, int] = {}
    for n in gold_names:
        b, j = parse_base_and_bit(n)
        if j is not None and b in gold_wires:
            gold_bits[b] = gold_bits.get(b, 0) + 1
    gate_bits: dict[str, list[tuple[int, str]]] = {}
    for n in gate_names:
        b, j = parse_base_and_bit(n)
        if j is not None:
            gate_bits.setdefault(b, []).append((j, n))
    out = []
    for b in sorted(gold_bits):
        width, offset = gold_wires[b]
        bits = sorted(gate_bits.get(b, []))
        if (1 < width <= max_bits and gold_bits[b] == width and 2 <= len(bits) < width
                and bits[-1][0] < offset + width):
            out.append((b, bits))
    return out


def small_register_ranges(
    gold_names: set[str], gold_wires: Wires, gold_upto: set[str], max_bits: int, skip=frozenset()
) -> list[tuple[str, int, int]]:
    """(gold wire, lo, hi): maximal runs of adjacent register bit positions of a wire, 2..max_bits long
    (a whole small register, or the registered stages of a pipeline array whose first stage is
    combinational). Wider runs are skipped: one candidate per value does not scale, and the fields of a
    flattened struct are not known here."""
    pos: dict[str, set[int]] = {}
    for name in gold_names:
        base, bit = parse_base_and_bit(name)
        if base not in gold_wires:
            base, bit = name, None
        if base in skip or gold_wires[base][0] <= 1:
            continue
        pos.setdefault(base, set()).add(bit_position(gold_wires, gold_upto, base, bit))
    out = []
    for base in sorted(pos):
        ps = sorted(pos[base])
        lo = prev = ps[0]
        for p in ps[1:] + [None]:
            if p is None or p != prev + 1:
                if 2 <= prev - lo + 1 <= max_bits:
                    out.append((base, lo, prev))
                lo = p
            prev = p
    return out


def guarded_equalities(
    pairs: list[Pair], gold_names: set[str], gold_wires: Wires, gold_upto: set[str], edge_bits: int
) -> list[tuple[str, int, int, str, "int | None"]]:
    """(gold wire, lo, hi, guard wire, guard position or None): for every run [lo, hi] of at least two
    adjacent paired bit positions of a multi-bit gold register, the guards to try. A guard is a 1-bit gold
    register of the same scope (hierarchical prefix; a `valid` next to its data), or one of the edge_bits
    lowest / highest register bits of the wire itself (a valid bit packed with its data, first or last
    field of a struct). Valid bits in the middle of a wide array of structs are not covered."""
    pos: dict[str, set[int]] = {}
    for base, local, gate_full in pairs:
        if gate_full is not None and local is not None:
            pos.setdefault(base, set()).add(local)
    regpos: dict[str, list[int]] = {}
    one: dict[str, list[str]] = {}
    for name in gold_names:
        base, bit = parse_base_and_bit(name)
        if base not in gold_wires:
            base, bit = name, None
        if gold_wires[base][0] <= 1:
            one.setdefault(base.rpartition(".")[0], []).append(base)
        else:
            regpos.setdefault(base, []).append(bit_position(gold_wires, gold_upto, base, bit))
    out = []
    for base in sorted(pos):
        ps = sorted(pos[base])
        own = sorted(regpos.get(base, []))
        edge = sorted(set(own[:edge_bits] + own[-edge_bits:])) if edge_bits else []
        guards = [(g, None) for g in sorted(one.get(base.rpartition(".")[0], []))] + [(base, j) for j in edge]
        lo = prev = ps[0]
        for p in ps[1:] + [None]:
            if p is None or p != prev + 1:
                if prev - lo + 1 >= 2:
                    out += [(base, lo, prev, g, j) for g, j in guards]
                lo = p
            prev = p
    return out


def glob_escape(s: str) -> str:
    return re.sub(r"([*?\[\]])", r"\\\1", s)


def safe_ident(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def ihv_wire(base: str, side: str) -> str:
    """The miter wire that carries the gold (side "a") or gate (side "b") copy of register `base`."""
    return f"ihv_{safe_ident(base)}_{side}"


def unsplit_vectors(names: list[str], wires: Wires) -> list[str]:
    """Wires of which some of `names` are bits (`w[i]`) while `w` is still one multi-bit wire."""
    out = set()
    for n in names:
        base, bit = parse_base_and_bit(n)
        if n not in wires and bit is not None and wires.get(base, (1, 0))[0] > 1:
            out.add(base)
    return sorted(out)


def expose_script(gold_bases: list[str], gate_exposed: list[str], public: dict[str, str],
                  gate_wires: "Wires | None" = None) -> list[str]:
    """yosys commands that turn the compared wires into ports."""
    lines = [""]
    # internal ($) names cannot be connected by name from the miter: give them public names first
    renames = [f"rename {n} \\{public[n]}" for n in gate_exposed if n.startswith("$")]
    if renames:
        lines += ["cd gate_top", *renames, "cd .."]
    # gate bits named `w[i]` that are bits of a multi-bit wire `w` (a netlist whose nets are not all
    # split, e.g. submodule ports kept whole by splitnets and then flattened): split exactly those wires.
    # splitnets names every bit by its HDL index (offset, upto), as the bit names here are; it changes
    # names only, not connectivity
    split = unsplit_vectors([n for n in gate_exposed if not n.startswith("$")], gate_wires or {})
    if split:
        lines.append("splitnets " + " ".join(f"gate_top/w:\\{glob_escape(b)}" for b in split))
    lines.append(
        "expose " + " ".join(f"gold_top/w:\\{glob_escape(b)}" for b in gold_bases)
    )
    lines.append(
        "expose "
        + " ".join(f"gate_top/w:\\{glob_escape(public[n])}" for n in gate_exposed)
    )
    return lines


def pair_lines(pairs: list[Pair]) -> tuple[list[str], list[str], dict[str, str]]:
    """Gold bit == gate bit. Returns (gate port connections, asserts, gate bit -> the ihv wire bit it
    is connected to)."""
    ports_b: list[str] = []
    asserts: list[str] = []
    gate_expr: dict[str, str] = {}
    for base, local, gate_full in pairs:
        wire_a, wire_b = ihv_wire(base, "a"), ihv_wire(base, "b")
        if gate_full is None:
            # gold-only register bit: "stays constant", 0 (init value after setundef -init -zero, or a
            # reset value) or 1 (a reset value); the base case drops the one that does not hold
            bit_a = wire_a if local is None else f"{wire_a}[{local}]"
            asserts.append(f"      assert({bit_a} == 1'b0);")
            asserts.append(f"      assert({bit_a} == 1'b1);")
        elif local is None:
            ports_b.append(f"      , .\\{gate_full} ({wire_b})")
            asserts.append(f"      assert({wire_a} == {wire_b});")
            gate_expr[gate_full] = wire_b
        else:
            ports_b.append(f"      , .\\{gate_full} ({wire_b}[{local}])")
            asserts.append(
                f"      assert({wire_a}[{local}] == {wire_b}[{local}]);"
            )
            gate_expr[gate_full] = f"{wire_b}[{local}]"
    return ports_b, asserts, gate_expr


def fsm_lines(
    fsm, gold_wires: Wires, public: dict[str, str], gate_expr: dict[str, str]
) -> tuple[list[str], list[str], list[str]]:
    """One candidate per gate state bit and gold state value: "gate bit j is set exactly when the gold
    state is k". With one-hot recoding one k per bit holds; Houdini drops the others.
    Returns (declarations, gate port connections, asserts) and adds the new connections to gate_expr."""
    decls: list[str] = []
    ports_b: list[str] = []
    asserts: list[str] = []
    for base, bits in fsm:
        width, _offset = gold_wires[base]
        wire_a, wire_f = ihv_wire(base, "a"), ihv_wire(base, "fsm_b")
        new_bits = [g for _, g in bits if g not in gate_expr]
        if new_bits:  # a gate port can be connected once: reuse the bit-pair connection if any
            decls.append(f"wire [{len(new_bits) - 1}:0] {wire_f};")
            for i, g in enumerate(new_bits):
                ports_b.append(f"      , .\\{public[g]} ({wire_f}[{i}])")
                gate_expr[g] = f"{wire_f}[{i}]"
        for _, g in bits:
            for k in range(2**width):
                asserts.append(
                    f"      assert({gate_expr[g]} == ({wire_a} == {width}'d{k}));"
                )
        # "the gold state never takes value k": holds for unused codes, which the step case would
        # otherwise start from (the gate's all-zero one-hot state has no gold counterpart)
        for k in range(2**width):
            asserts.append(f"      assert({wire_a} != {width}'d{k});")
    return decls, ports_b, asserts


def recoded_asserts(recoded, gold_wires: Wires, gate_expr: dict[str, str]) -> list[str]:
    """ "While the gold state is k, gate bit j is 0" and "... is 1", for every k and j: whatever the
    new encoding is, a reachable gold state fixes every gate state bit, and Houdini keeps that half.
    (If the register only lost constant bits, the half that repeats the bit equalities.)
    Also "the gold state is never k", as in fsm_lines: for an unused code both halves hold."""
    asserts: list[str] = []
    for base, bits in recoded:
        width, _offset = gold_wires[base]
        wire_a = ihv_wire(base, "a")
        for k in range(2**width):
            for _, g in bits:
                asserts.append(f"      assert({wire_a} != {width}'d{k} || !{gate_expr[g]});")
                asserts.append(f"      assert({wire_a} != {width}'d{k} || {gate_expr[g]});")
        for k in range(2**width):
            asserts.append(f"      assert({wire_a} != {width}'d{k});")
    return asserts


def range_asserts(ranges, gold_wires: Wires) -> list[str]:
    """ "These register bits never hold the value k": true for the codes a register cannot reach
    (unused enum values, counter values past the limit). On such codes RTL and netlist may differ
    (out-of-range index, `x` in a default branch: don't-cares for synthesis), so no equality between
    gold and gate registers is inductive from a state that holds one. Houdini keeps the unreachable k."""
    asserts: list[str] = []
    for base, lo, hi in ranges:
        width = gold_wires[base][0]
        wire_a, n = ihv_wire(base, "a"), hi - lo + 1
        sel = wire_a if n == width else f"{wire_a}[{hi}:{lo}]"
        for k in range(2**n):
            asserts.append(f"      assert({sel} != {n}'d{k});")
    return asserts


def guarded_asserts(guarded) -> list[str]:
    """ "guard -> these gold bits equal their gate bits", in both polarities of the guard. A register
    that loads its data whether or not the data is valid holds don't-care values in between (e.g.
    an out-of-range read, which RTL and netlist resolve differently): the plain equality is false
    in reachable states, the one qualified by the right valid bit holds. Houdini keeps those."""
    asserts: list[str] = []
    for base, lo, hi, guard, gpos in guarded:
        wire_a, wire_b = ihv_wire(base, "a"), ihv_wire(base, "b")
        eq = f"{wire_a}[{hi}:{lo}] == {wire_b}[{hi}:{lo}]"
        g = ihv_wire(guard, "a") + ("" if gpos is None else f"[{gpos}]")
        asserts.append(f"      assert(!{g} || ({eq}));")
        asserts.append(f"      assert({g} || ({eq}));")
    return asserts


def write_output_files(
    pairs: list[Pair], out_paths: dict[str, Path], gold_wires: Wires, fsm=(), ranges=(), guarded=(),
    recoded=(), gate_wires: "Wires | None" = None
) -> None:
    """fsm: (gold base, [(gate bit index, gate bit name)]) of re-encoded state registers, see
    fsm_state_registers. ranges: (gold base, lo, hi) bit positions of small gold registers, see
    small_register_ranges. guarded: see guarded_equalities. recoded: like fsm, see
    recoded_state_registers."""
    gold_bases = sorted({p[0] for p in pairs} | {f[0] for f in fsm} | {r[0] for r in ranges}
                        | {x[3] for x in guarded} | {f[0] for f in recoded})
    gate_exposed = sorted(
        {p[2] for p in pairs if p[2] is not None} | {g for f in fsm for _, g in f[1]}
        | {g for f in recoded for _, g in f[1]}
    )
    public = {n: (f"ihv_anon_{i}" if n.startswith("$") else n) for i, n in enumerate(gate_exposed)}

    decl_lines = [""]
    ports_a_lines = [""]
    for base in gold_bases:
        width, _offset = gold_wires[base]
        width_decl = "" if width <= 1 else f"[{width - 1}:0] "
        decl_lines.append(f"wire {width_decl}{ihv_wire(base, 'a')};")
        decl_lines.append(f"wire {width_decl}{ihv_wire(base, 'b')};")
        ports_a_lines.append(f"      , .\\{base} ({ihv_wire(base, 'a')})")

    pair_ports, pair_asserts, gate_expr = pair_lines(pairs)
    fsm_decls, fsm_ports, fsm_asserts = fsm_lines(fsm, gold_wires, public, gate_expr)
    decl_lines += fsm_decls
    ports_b_lines = ["", *pair_ports, *fsm_ports]
    assert_lines = [
        "",
        *pair_asserts,
        *fsm_asserts,
        *recoded_asserts(recoded, gold_wires, gate_expr),
        *range_asserts(ranges, gold_wires),
        *guarded_asserts(guarded),
    ]

    out_paths["expose"].write_text(
        "\n".join(expose_script(gold_bases, gate_exposed, public, gate_wires)) + "\n")
    out_paths["decls"].write_text("\n".join(decl_lines) + "\n")
    out_paths["ports_a"].write_text("\n".join(ports_a_lines) + "\n")
    out_paths["ports_b"].write_text("\n".join(ports_b_lines) + "\n")
    out_paths["asserts"].write_text("\n".join(assert_lines) + "\n")


def generate_assert_files(
    gold_netlist,
    gate_netlist,
    expose,
    decls,
    ports_a,
    ports_b,
    asserts,
    match_gate_wires=False,
    const_candidates=False,
    fsm_candidates=False,
    fsm_max_bits=6,
    range_candidates=False,
    range_max_bits=6,
    guarded_candidates=False,
    guard_edge_bits=2,
):
    if not gold_netlist.exists():
        sys.exit(f"{gold_netlist} not found")
    if not gate_netlist.exists():
        sys.exit(f"{gate_netlist} not found")

    out_paths = {
        "expose": expose,
        "decls": decls,
        "ports_a": ports_a,
        "ports_b": ports_b,
        "asserts": asserts,
    }

    gold_content = gold_netlist.read_text()
    gold_lines = get_module_lines(gold_content, "gold_top")
    gold_wires, gold_ports = parse_wires_and_ports(gold_lines)
    gold_upto = upto_wires(gold_lines)
    gold_cells = parse_register_cells(gold_lines, gold_wires, gold_upto)
    gold_names = names_from_cells(gold_cells, gold_wires, gold_ports)

    gate_content = gate_netlist.read_text()
    gate_lines = get_module_lines(gate_content, "gate_top")
    gate_wires, gate_ports = parse_wires_and_ports(gate_lines)
    gate_cells = parse_register_cells(gate_lines, gate_wires, upto_wires(gate_lines))
    gate_names = names_from_cells(gate_cells, gate_wires, gate_ports)

    def local_of(base: str, bit: "int | None") -> "int | None":
        """Bit position in the gold wire (and its ihv_*_a copy) of HDL index bit."""
        if gold_wires[base][0] <= 1:
            return None
        return bit_position(gold_wires, gold_upto, base, bit)

    def bit_name(base: str, local: "int | None") -> str:
        return base if local is None else f"{base}[{hdl_index(gold_wires, gold_upto, base, local)}]"

    def pair_of(name: str, gate: "str | None") -> Pair:
        """The pair of gold register bit `name` (or whole wire, if `name` is one) with a gate bit."""
        base, bit = parse_base_and_bit(name)
        if base not in gold_wires:
            base, bit = name, None
        return (base, local_of(base, bit), gate)

    matched_names = gold_names & gate_names
    name_pairs: list[Pair] = [pair_of(name, name) for name in matched_names]

    src_pairs = match_by_src(
        gold_cells, gate_cells, gold_wires, gold_ports, gate_ports, matched_names, gold_upto
    )

    wire_pairs: list[Pair] = []
    if match_gate_wires:
        # gold register without a gate flop of that name: pair it with the gate *wire* of
        # that name (buffered copy of a flop, or logic where synthesis merged/removed the flop)
        covered = matched_names | {bit_name(base, pos) for base, pos, _ in src_pairs}
        gate_wire_bits = {
            b
            for w in gate_wires
            for b in match_wire_widhts(f"\\{w}", gate_wires)
            if b not in gate_ports
        }
        wire_pairs = [pair_of(name, name) for name in sorted(gold_names - covered) if name in gate_wire_bits]

    const_pairs: list[Pair] = []
    if const_candidates:
        # gold register bit with no gate counterpart at all (synthesis found it constant and removed
        # it): candidates "stays 0" / "stays 1" (see write_output_files), else unconstrained in the
        # induction step
        covered = {bit_name(base, pos) for base, pos, _ in name_pairs + src_pairs + wire_pairs}
        const_pairs = [pair_of(name, None) for name in sorted(gold_names - covered)]

    all_pairs = sorted(
        name_pairs + src_pairs + wire_pairs + const_pairs,
        key=lambda p: (p[0], -1 if p[1] is None else p[1], p[2] or ""),
    )

    paired_gate = {p[2] for p in name_pairs + src_pairs + wire_pairs if p[2] is not None}
    fsm = (
        fsm_state_registers(gold_names, gold_wires, gate_names, fsm_max_bits, paired_gate,
                            anonymous_registers(gate_lines))
        if fsm_candidates
        else []
    )
    recoded = (
        recoded_state_registers(gold_names, gold_wires, gate_names, fsm_max_bits)
        if fsm_candidates
        else []
    )
    ranges = (
        small_register_ranges(gold_names, gold_wires, gold_upto, range_max_bits,
                              {f[0] for f in fsm + recoded})
        if range_candidates
        else []
    )
    guarded = (
        guarded_equalities(all_pairs, gold_names, gold_wires, gold_upto, guard_edge_bits)
        if guarded_candidates
        else []
    )
    write_output_files(
        all_pairs, out_paths=out_paths, gold_wires=gold_wires, fsm=fsm, ranges=ranges, guarded=guarded,
        recoded=recoded, gate_wires=gate_wires
    )
