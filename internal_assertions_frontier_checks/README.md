# internal_assertions_frontier_checks

Does telling a formal solver that internal registers match (not just outputs) let it verify bigger designs before it times out?

For each design we build a "gold" (RTL) and a "gate" (post-synthesis, plain Yosys or full OpenROAD-flow-scripts) netlist, then check equivalence via a `miter` in two flavors: **MI**, a plain I/O miter, and **IA**, the same miter plus asserts (auto-generated from diffing the two RTLIL netlists) that internal registers match too. Instead of one fixed size, we binary-search a scaling parameter to find the **frontier** — the largest value that still `PASS`es within a timeout — separately for MI and IA, to see how much further internal asserts push it.

## Layout

| Folder | Design | Swept parameter(s) |
|---|---|---|
| [`corescore/`](corescore/README.md) | Multi-core SERV RISC-V SoC (FuseSoC) | core count |
| [`ol_arb_prio/`](ol_arb_prio/README.md) | open-logic priority arbiter (VHDL) | width, latency |
| [`ol_arb_rr/`](ol_arb_rr/README.md) | open-logic round-robin arbiter (VHDL) | width |
| [`xorgrid/`](xorgrid/README.md) | synthetic register-grid stress test | grid size, control bits, routing distance |

Each axis runs against both a plain Yosys synth and an ORFS netlist.

`_common/` is the shared harness (frontier search, `sby` runner, IA-assert generator, plotting). `sky130/` is the PDK timing lib ORFS runs need. `orfs/` is a throwaway sparse clone of OpenROAD-flow-scripts, fetched on demand — don't hand-edit it.

## Running

```
make all          # every benchmark folder
make corescore    # just one
make orfs         # pre-fetch OpenROAD-flow-scripts
make clean        # wipe run/ output everywhere
```

Each folder is really just `uv run find_max_parameter.py` (deps included inline), so that works too without `make`. Runs are slow — every solver runs at every step of the search, and the first run also builds ORFS.

**Needs:** `uv`, `yosys`/`sby` (with the `slang` and `ghdl` plugins) plus whatever solver backends the `sby` tasks call for (ABC, AIGER provers, BTOR2 model checkers, a handful of SMT solvers), `fusesoc` (corescore only), and network access the first time.

**Output:** `run/results.csv` and `run/plots/*.png` (per-benchmark cactus plots plus a cross-benchmark MI-vs-IA scatter/bar chart).

## Related

[`../internal_assertions/`](../internal_assertions/README.md) checks the same MI/IA idea at one fixed size across many real IP cores, plus mutation testing. This suite is its scaling/"how far can we push it" companion.
