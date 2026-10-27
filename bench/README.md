# bench/

Each design is described by one `design.toml`. `run.py` builds the gold/gate pair for each point of a design in
each gate flow (flavor) and runs the checks on it, once per toolchain.

```
python3 bench/run.py ol_arb_rr                                  # table: every point, both flavors, all checks
python3 bench/run.py ol_arb_rr --ladders                        # the design's ladders (scaling set)
python3 bench/run.py ol_fifo_sync --point Depth_g=4,Width_g=8 --flavors yosys   # one point, one flavor
python3 bench/run.py ol_arb_rr --tools a=/opt/suiteA/bin --tools b=/opt/suiteB/bin   # compare two tool versions
python3 bench/kpi.py table                                      # recompute the scores (run.py does this at the end)
python3 bench/tests.py                                          # self-tests, a few minutes
```

The cva6 sources are a submodule. Only the parts its file list needs have to be checked out:
```
git submodule update --init bench/designs/cva6/src/cva6
git -C bench/designs/cva6/src/cva6 submodule update --init --recursive core/cvfpu core/cache_subsystem/hpdcache
```

| path | what |
|---|---|
| `designs/<name>/design.toml` | a design (format below); its sources are in `src/`, shared sources in `designs/_lib/` |
| `platforms/sky130hd` | the liberty file used by both gate flows |
| `design.py` | loads a design.toml, fills in defaults, refuses what is not supported, lists the points |
| `flow.py` | builds a bundle `build/<design>/<point>_<flavor>/` with `gold.il`, `gate.il` and `case.json` |
| `checks.py` | the generated miter and cover, and the checks `eqy`, `sby_mi`, `cover` and the gate mutants |
| `runner.py` | runs the tools under the memory cap: the racing sby engines, and eqy with its verdict |
| `mutate.py` | makes the gate mutants with yosys' `mutate` |
| `kpi.py` | the score: `s` per row in results.csv, and the summary in `kpi.csv` |
| `run.py` | runs designs × flavors × points × toolchains × checks, results go to `results/<experiment>/results.csv` |

`build/` and `work/` (the tools' work dirs) are not in git. A design's name is its path under `designs/`. Designs
can be nested, as in `group/variant`, and the first part of the name is the design's group in the score.

## design.toml

| field | default | meaning |
|---|---|---|
| `top` | required | top module or entity |
| `exercises` | `[]` | the RTL features the design covers |
| `[source] frontend` | required | `ghdl` or `slang` |
| `[source] files` / `flist` | one of them | the sources in order, or a `-F` file list, relative to the design dir (to `{out}` with `generate`) |
| `[source] args`, `defines`, `[source.env]` | empty | frontend arguments, `-D` macros, environment; `{design}` is the design dir |
| `[source] generate` | none | a command run per point before the frontend, with `{design}`, `{out}` and `{<param>}` filled in; the parameters then only go to the command |
| `[params.NAME] values` | none | generics or parameters; the table points are their cross product |
| `[points] require` | none | a filter on the cross product, e.g. `"MaxShift_g <= Width_g"` (arithmetic, comparisons, and/or/not) |
| `[[ladders]] name, points, timeout` | design's timeout | a ladder: parameter tables in ladder order |
| `[[clocks]] name, edge, period_ns` | `posedge`, 10 | the edge is used by the miter, the period by the SDC for ORFS |
| `[[resets]] name, clock, active, hold` | `hold = 2` | the reset is active for `hold` clock edges, then free |
| `[compare] exclude` | `[]` | `{port, why}`: an output that is not compared |
| `[cover] depth, engine` | 64, `smtbmc yices` | cover depth in sby steps (one clock cycle is 2 steps after `clk2fflogic`), and `smtbmc` with yices, boolector, bitwuzla or z3 |
| `[power_up] gate, why` | `free` | `rtl_init` keeps the RTL's initial values in the gate and needs a `why` |
| `[flows.yosys] enabled`, `[flows.orfs] enabled, config` | on, `[]` | turns a flavor off; extra lines for ORFS's config.mk |
| `[limits] timeout, build_timeout` | 300, 3600 | seconds per check and per build step |

The loader refuses unknown keys, an `exclude` or `rtl_init` without a real `why`, a `require` with other syntax or
one that removes every point, and `[compare] settle` and `valid_guard`, which are not implemented yet.

A point that cannot be built gets a `build` row and is not scored. It is UNSUPPORTED if the gold netlist has flops
on more than one clock net (separate clock inputs, or a gated or divided clock) or latches; asynchronous resets are
supported. It is an ERROR if a build step fails, or if the gold or gate netlist has conflicting drivers, which is a
defect of the benchmark.

## Flavors

`yosys` runs `synth`, maps to sky130hd flip-flops and cells (`dfflibmap`, `abc`), and writes the gate as RTLIL.
`orfs` flattens the RTL to Verilog, runs the synthesis step of ORFS (`1_2_yosys.v`) with a generated SDC, and reads
the netlist back with slang. ORFS is a checkout in `bench/orfs`, or `$ORFS_HOME`; its submodules are not needed:
```
git clone https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts bench/orfs && git -C bench/orfs checkout a15fd19
```

In both flavors the gate flops start free (`setattr -unset init`), unless `[power_up] gate = "rtl_init"`.

## Checks

`eqy` uses one fixed config for every design: `splitnets`, `bind *`, sby with `abc pdr`, and the pdr timeout set to
the limit. It applies no reset.

`sby_mi` is a generated miter, proven with pdr, suprove and rIC3; the first engine with a verdict stops the others.
It compares every output at every step once all reset sequences are over. Gold flops the RTL leaves uninitialized
start at 0, gate flops start free. Undriven wires read 0 (`setundef -undriven -zero`), the clock is modelled with
`clk2fflogic`, and inout ports are refused.

`cover` runs on the gold design alone. For each output port it covers that all bits are defined (like eqy's
COVER_DEF_GOLD_OUTPUTS, under `xprop -formal`) after the reset sequence, up to `[cover] depth`. It stops once every
port is covered, so a large depth only costs time where a port stays undefined. The result is COVERED, NOT_COVERED
with the ports, or UNKNOWN on a timeout.

`mutants` checks the gate mutants of every point that eqy or sby_mi PASSed (mutate.py with seed 1, liberty pin
directions, at most one flip-flop away from an output). They run in order until one is known to differ, i.e.
sby_mi FAILs it. The largest point of a series that PASSed within 60 s gets all 4 of its mutants checked. Mutant rows
have the variant `mNN`.

## Ladders

`run.py --ladders` runs each ladder in order with its timeout; the rows have the ladder's name as `axis`. Once a
check has 2 unsolved sizes in a row, its larger sizes get NOT_RUN rows (s = 2). A size that fails to build is not
scored.

## Score

Each instance scores `s = t / T` if it is solved within its limit `T`, and 2 otherwise. A PASS counts as solved if
its bundle is COVERED. A FAIL counts if it holds from reset: an sby_mi FAIL, or an eqy FAIL on netlists that sby_mi
FAILs too. sby_mi counts once per bundle, with its best engine. The time-to-solve set (table rows) has one group per
design group, the scaling set (ladder rows) one group per design, ladder and flavor. S_time and S_size are the means
of their group scores, and S is the mean of the two.

The `gate` column in kpi.csv is VOID if the check PASSed a mutant known to differ (sby_mi FAILs it and PASSed the
original). It also counts the PASS points without a FAIL on such a mutant (unverified), lists the PASS points that
sby_mi FAILs from reset (usually a register without reset at an output, since gold starts at 0 and the gate free),
and the mutant PASSes that may be equivalent mutants. Other exclusions for benchmark defects are not modelled.

Not yet included: importing older results.
