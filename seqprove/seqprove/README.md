# seqprove: incremental Houdini k-induction over miter asserts

Proves a gold/gate miter by k-induction over its own asserts (the *properties*) plus generated internal
equalities (the *candidates*), with `yosys-smtbmc --incremental`. Results and comparisons with sby and eqy
are in `../../BENCHMARK_SUMMARY.md`, section 3.

    # model from a benchmark run dir, then the proof
    python3 build_model.py ../../internal_assertions_frontier_checks/ol_fifo_sync/run/D4_W8_T300 /tmp/m \
        --regen --match-gate-wires --const-candidates
    python3 seq_prove.py /tmp/m/model.smt2 --candidates asserts.vh --src /tmp/m/asserts.vh \
        --k 2 --chunk 16 --model --out /tmp/m/prove --timeout 300

    # many cases: results in ../runs/<tag>/results.csv, models cached in ../runs/models/
    python3 run_bench.py cases/ab.txt --tag ab_auto --prove "--k 2 --chunk 16 --model"

    # frontier search per scaling axis, then a mutation test at each tool's largest PASS
    uv run frontier.py ol_pl_stage:Stages --tag TAG [--tool eqy|sby]
    uv run frontier_mutants.py --tag TAG

    # mutants of a netlist, run like any case list
    python3 mutate.py <gate.il> ../runs/mutants/<name> --module gate_top --n 20 --case "BENCH RUN asserts=new"

| file | role |
|---|---|
| `build_model.py` | run dir -> `model.smt2`: the run's sby script without `clk2fflogic`, clocked assert blocks as `always @*`, guards, candidate generation |
| `model.py` | reads the SMT2: asserts, registers, clock nets, layer of each assert |
| `session.py` | one `yosys-smtbmc --incremental` process |
| `houdini.py` | the proof loop; the soundness argument is in its docstring |
| `seq_prove.py` | CLI; `--out` writes `summary.json` and `checks.jsonl` (one line per solver check) |
| `run_bench.py` | build and prove a case list, optionally with sby and eqy |
| `frontier.py`, `frontier_mutants.py` | frontier search for seq_prove, eqy or plain sby; mutation test at the frontier |
| `compare.py`, `plot_compare.py`, `plot_frontier.py` | tables and figures from the results |
| `mutate.py` | mutants via yosys `mutate` |
| `cone_gap.py`, `explain_step.py` | diagnosis of an UNKNOWN: cone registers without a surviving candidate; one failing step check with its counterexample |
| `eqy_def_cover.py` | non-vacuity check of an eqy PASS: can every gold output be defined? |
| `vendor/smtbmc_incremental.py` | copied from a yosys checkout (not in OSS CAD Suite, commit not recorded), loaded via `PYTHONPATH`. One change: `check` passes `unknown` through |

## Algorithm

Every live assert is a retractable hypothesis at steps 0..K-1 of the step session. Asserts are checked in
chunks, in the base case (steps 0..K-1, or 0..K if the model reads `$initstate`) and in the step case at
step K. A failing assert is retracted, and sweeps repeat until one retracts nothing. `--model` drops every
live assert a sat model violates.

Layer 0 holds unconditional predicates over register reads (`q_a == q_b`, `q != 3'd5`), layer 1 everything
else. Layer-1 asserts are checked with the live layer-0 asserts also assumed at step K, so an output that is
logic over registers is checked without a full transition. `--layers off` puts everything in layer 0.

| option | effect |
|---|---|
| `--order values-first` | value constraints before register equalities: same fixpoint in fewer sweeps |
| `--wide-bits N`, `--wide-solver S` | asserts comparing at least N bits (default 64) are checked one at a time by S (default boolector) |
| `--query-timeout S` | a check over S seconds rebuilds the session and splits the chunk; a single assert that still times out is retracted. bitwuzla stops the check itself |
| `--timeout-siblings`, `--sibling-max M` | after a timeout, also retract the other bits of that register unchecked; names wider than M bits only lose their bits in the current chunk |
| `--session-mem-gb G` | rebuild a session that uses more than G GiB |
| `--defer-implied` | guarded equalities stay unused while the bit equalities that imply them are live, and are woken when one drops |
| `--drop-from RUN` | start without the candidates an earlier run dropped by a counterexample before its first timeout (same fixpoint) |
| `--resume-from RUN` | start without everything an unfinished run retracted; can lose a proof that run lost |

All of these only retract or reorder hypotheses, which is sound. Properties are never taken over from an
earlier run, and a timed-out property ends UNKNOWN, never PASS or FAIL.

## Results

`PASS`: all properties proven. `FAIL`: a property is false on a path from the initial state. `UNKNOWN`: some
property is not inductive with the live candidates, or a timeout. `ERROR`: unsupported model, failed vacuity
check or tool failure. A false candidate never causes FAIL; it is a wrong guess.

Built-in non-vacuity checks: the model has at least one property, the base session without goal is sat, and
the step session with all hypotheses (plus layer 0 at step K) and no goal is sat. `summary.json` lists
properties and candidates separately.

## Supported RTL

| construct | status |
|---|---|
| one posedge clock from a top-level input | supported; derived, gated, constant or multiple clocks are refused by build_model's clock guard, and seq_prove refuses more than one clock net |
| negedge flip-flops, latches, tristates | refused by build_model (`--allow-latches` models latches as sampled flip-flops) |
| async resets | the script's `async2sync`: sampled at the clock edge as in the sby flow, async timing is not checked |
| memories | candidates need `memory_map`; unmapped memories only warn. Memory port clock polarity is not checked |
| hierarchy, parameters, generate | frontend + `flatten`; an unflattened model is an ERROR |
| `$initstate` | the base case extends to step K |
| x/z, undriven | as the benchmark scripts set them (`setundef -zero`, `setundef -undriven -init -zero`) |
| blackboxes | `write_smt2` fails |
| reset sequences | `fminit -seq` is kept |
| clocked assert blocks with other logic | refused; only asserts, includes, preprocessor lines and `else $error(...)` are converted |
| VHDL (GHDL) | not tested |

## Candidate generation (build_model.py)

| option | candidates |
|---|---|
| `--regen` | `_common/generate_internal_asserts.py`: gold/gate register bits paired by name, HDL indices also for `upto` and offset wires |
| `--match-gate-wires` | a gold register without a same-named gate flip-flop vs the gate wire of that name |
| `--const-candidates` | a gold register bit without gate counterpart is constant: `== 1'b0` and `== 1'b1`, the base case drops the wrong one |
| `--range-candidates` | `register != k` for every value of each small gold register (2..6 bits): keeps the unreachable values, where RTL and netlist may differ. Fields inside wide struct registers are not covered |
| `--guarded-candidates` | `guard -> gold bits == gate bits` for multi-bit registers, guard = a 1-bit register of the same scope or an edge bit of the register, both polarities: for data that is a don't-care while not valid. Valid bits in the middle of wide struct arrays are not covered |
| `--fsm-candidates` | re-encoded state registers (gate bits beyond the gold width, e.g. one-hot): `gate_bit == (gold_state == k)` and `gold_state != k`; also registers the gate keeps fewer bits of. A re-encoding with the same bit count is not detected |
| `--output-bit-candidates` | one candidate per bit of each equality property `A == B`, in `<miter>_bits.vh` |
| `--regen-name KEY=FILE` | input names of other layouts, e.g. cva6: `gold=gold_out.il asserts=internal_helper_asserts.vh` |

Candidates are only hypotheses that Houdini checks; none changes what the properties claim.

## Tests

    python3 tests/run_tests.py     # 63 tiny designs with known answers, including build refusals

The comment above each case in `run_tests.py` says which corner case it covers.
