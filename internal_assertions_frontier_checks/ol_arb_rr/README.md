# ol_arb_rr

[open-logic](https://github.com/open-logic/open-logic)'s `olo_base_arb_rr` — a round-robin arbiter in VHDL, elaborated via Yosys's `ghdl` plugin. Same source tree and toolchain as [`ol_arb_prio`](../ol_arb_prio/README.md), but only one generic (`Width_g`) and its miter adds an `Out_Valid`/`Out_Ready` handshake.

`find_max_parameter.py` sweeps `Width_g`, finding the largest value that still formally verifies within 60s — plain Yosys synth and an ORFS variant, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make ol_arb_rr` from the parent folder. Needs the `ghdl` Yosys plugin on top of the [usual requirements](../README.md), since the design is VHDL.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
