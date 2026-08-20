# internal_assertions

Formal equivalence checking between gold (RTL) and gate-level netlists for a set of
benchmark designs, using [Yosys](https://github.com/YosysHQ/yosys)/`eqy`/`sby`. Each
benchmark's synthesized gate netlist is checked against the RTL both with plain I/O
miters and with "extra asserts" miters that also assert internal register equivalence,
plus mutation checks that inject a synthesis bug and verify the miter actually catches
it. Netlists can come from a plain Yosys synth or from a full
[ORFS](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts) place-and-route
flow (`-orfs` target variants).

Each benchmark lives in its own subdirectory with its own `Makefile` defining the
targets it supports (`sby`, `eqy`, `custom-miter`, `custom-miter-extra-asserts`,
`mutation-check`, etc., plus `-orfs` variants). `dblclockfft/` groups several
sub-benchmarks the same way the top-level `Makefile` groups all of them.

## Top-level Makefile

- `make all` / `make <target>` — run `<target>` (e.g. `custom-miter`) across every
  benchmark subdirectory that defines it.
- `make orfs` — sparse-clone OpenROAD-flow-scripts into `orfs/`, needed for `-orfs`
  targets.
- `make run-all` — run every check target across all benchmarks. Slow, disk-hungry,
  and not resumable.
- `make run-incremental` — same coverage as `run-all`, but driven by
  `run_incremental.py`: checkpoints progress into `report.json` after every single
  target so an interrupted run resumes instead of restarting, and cleans up each
  benchmark's build artifacts once its targets are done to keep disk usage bounded.
  Run `python3 run_incremental.py --help` for options (`--leaf`, `--yosys-only`,
  `--dry-run`, `--no-clean`).
- `make report` — print the results already recorded in `report.json` as a table
  (via `report.py`), without running or collecting anything itself.
- `make clean` — remove `run/` in every benchmark subdirectory.
