# internal_assertions_frontier_checks

Does telling a formal solver that internal registers match (not just outputs) let it verify bigger designs before it times out?

For each design we build a "gold" (RTL) and a "gate" (post-synthesis, plain Yosys or full OpenROAD-flow-scripts) netlist, then check equivalence via a `miter` in two flavors: **MI**, a plain I/O miter, and **IA**, the same miter plus asserts (auto-generated from diffing the two RTLIL netlists) that internal registers match too. Instead of one fixed size, we binary-search a scaling parameter to find the **frontier** — the largest value that still `PASS`es within a timeout — separately for MI and IA, to see how much further internal asserts push it.

## Layout

| Folder | Design | Swept parameter(s) |
|---|---|---|
| [`corescore/`](corescore/README.md) | Multi-core SERV RISC-V SoC (FuseSoC) | core count |
| [`fft64/`](fft64/README.md) | r22sdf 64-point pipelined FFT (radix-2² SDF) | datapath width |
| [`ol_arb_prio/`](ol_arb_prio/README.md) | open-logic priority arbiter (VHDL) | width, latency |
| [`ol_arb_rr/`](ol_arb_rr/README.md) | open-logic round-robin arbiter (VHDL) | width |
| [`xorgrid/`](xorgrid/README.md) | synthetic register-grid stress test | grid size, control bits, routing distance |

Each axis runs against both a plain Yosys synth and an ORFS netlist.

`_common/` is the shared harness (frontier search, `sby` runner, IA-assert generator, plotting). It also holds `tasks.sby.in`, the one shared `[tasks]`/`[options]`/`[engines]` config every benchmark uses; a folder that needs to differ (e.g. a deeper BMC `depth`) drops a small `tasks.sby.in` fragment of its own that is merged over the shared one at render time. `sky130/` is the PDK timing lib ORFS runs need. `orfs/` is a throwaway sparse clone of OpenROAD-flow-scripts, fetched on demand — don't hand-edit it.

## Running

```
make all          # every benchmark folder
make corescore    # just one
make orfs         # pre-fetch OpenROAD-flow-scripts
make summary      # aggregate every completed benchmark into summary/ (see below)
make clean        # wipe run/ output everywhere
```

Each folder is really just `uv run find_max_parameter.py` (deps included inline), so that works too without `make`. Runs are slow — every solver runs at every step of the search, and the first run also builds ORFS.

**Needs:** `uv`, `yosys`/`sby` (with the `slang` and `ghdl` plugins) plus whatever solver backends the `sby` tasks call for (ABC, AIGER provers, BTOR2 model checkers, a handful of SMT solvers), `fusesoc` (corescore only), and network access the first time.

**Output:** `run/results.csv` and `run/plots/*.png` (an MI-vs-IA heatmap, a per-engine scatter grid, and a per-engine grouped bar chart).

## Cross-benchmark summary

Each benchmark directory's own `run/plots/` only compares flavors *within*
that directory (e.g. corescore's plain-Yosys sweep vs. its ORFS sweep).
Since every design sweeps a different parameter (core count, width,
grid size...), the one number they all share is synthesized cell count,
so that's the x-axis for comparing across designs. `make summary` (or
`uv run _common/summarize.py`) aggregates every benchmark directory's
`run/results.parquet` into `summary/`:

- `summary/results.parquet` / `.csv` — every benchmark's rows, unioned,
  tagged with which directory they came from.
- `summary/plots/suite_cell_diff_heatmap.png` — engines × designs grid of
  `log2(IA / MI)` max solvable cells, diverging colors centered at 0. One
  row per engine (nothing is pooled across engines); scales to any number
  of designs and the log ratio keeps one outlier from flattening the rest.
- `summary/plots/suite_scatter.png` — MI cells vs. IA cells, one small-
  multiple panel per engine, points colored by which variant wins.
- `summary/plots/suite_cells_bars.png` — one grouped-bar panel per engine,
  a bar per design giving the geo-mean (over that design's synthesis axes)
  of the largest cell count solved, MI and IA paired. Log y-axis.

Every plot keeps the solver (engine) as an explicit dimension — a curve or
number pooled over solvers of very different character isn't meaningful, so
there is no cross-solver cactus, leaderboard, or aggregate.

It only reads already-produced `results.parquet` files (skipping, with a
note, any benchmark that hasn't completed a sweep yet), so it's cheap to
rerun any time and doesn't need `yosys`/`sby`/ORFS.

## Disk usage

A finished `sby` task leaves behind ~1GB of solver-internal state
(`model/`, `src/`, `engine_0/`, ...) that's never read again once its
`PASS`/`FAIL`/etc. marker file exists. Once both the MI and IA frontier
searches for a task have finished exploring every parameter value they'll
ever visit, that state is pruned automatically, and a compact summary
(cell count, result, timings) is kept in `run/results_cache.json` instead
— shrinking a finished `run/` tree by ~99% without affecting the "skip
already-run work" behavior (still driven by the marker files, which are
kept). This happens as a normal side effect of running `find_max_parameter.py`.

To shrink a `run/` tree that predates this — or to reclaim disk without
re-running a whole sweep — use the standalone migration script, which reads
existing marker files directly and needs no `yosys`/`sby`/ORFS:

```
uv run _common/migrate_cache.py                 # dry run, every benchmark
uv run _common/migrate_cache.py --apply          # actually migrate + prune
uv run _common/migrate_cache.py corescore --apply  # just one benchmark
```

It only ever touches a task's own already-finished workdir (never
`gold.il`/`gate.il`/`stat.txt` etc., which stay needed by any not-yet-run
task at that same parameter value), and is safe to re-run.

## Related

[`../internal_assertions/`](../internal_assertions/README.md) checks the same MI/IA idea at one fixed size across many real IP cores, plus mutation testing. This suite is its scaling/"how far can we push it" companion.
