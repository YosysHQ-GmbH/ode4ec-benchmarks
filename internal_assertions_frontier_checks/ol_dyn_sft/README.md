# ol_dyn_sft

[open-logic](https://github.com/open-logic/open-logic)'s `olo_base_dyn_sft` — a dynamic (runtime-controlled) shifter in VHDL, elaborated via Yosys's `ghdl` plugin. `Direction_g` (a VHDL `string`, "LEFT" or "RIGHT") is fixed to `"LEFT"` for all sweeps — it's not a scalable size, mirroring how [ol_pl_stage](../ol_pl_stage)'s `UseReady_g` and [ol_arb_wrr](../ol_arb_wrr)'s `Latency_g` are fixed. `SelBitsPerStage_g`/`SignExtend_g` stay at their VHDL defaults.

The VHDL entity also asserts `MaxShift_g <= Width_g`, so the two remaining generics can't be swept fully independently:
- **Width Scaling**: `MaxShift_g` fixed at `4`, `Width_g` swept starting no lower than `4` (`min_n=4`), so the constraint always holds.
- **MaxShift Scaling**: `Width_g = 2 * MaxShift_g` (computed alongside the swept value), keeping `Width_g` comfortably above `MaxShift_g` at every step.

Each finds the largest value that still formally verifies within 60s — plain Yosys synth and an ORFS variant, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make ol_dyn_sft` from the parent folder. Needs the `ghdl` Yosys plugin on top of the [usual requirements](../README.md), since the design is VHDL.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
