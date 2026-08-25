# ol_pl_stage

[open-logic](https://github.com/open-logic/open-logic)'s `olo_base_pl_stage` — a pipeline/register stage with handshake in VHDL, elaborated via Yosys's `ghdl` plugin. Two generics, `Width_g` and `Stages_g`, are swept independently; the third generic, `UseReady_g` (VHDL `boolean`), is fixed to `true` for all sweeps (the richer, backpressure-capable datapath) rather than exposed as a sweep axis.

`find_max_parameter.py` runs both sweeps (width fixed-stages, stages fixed-width), finding the largest value that still formally verifies within 60s — plain Yosys synth and an ORFS variant, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make ol_pl_stage` from the parent folder. Needs the `ghdl` Yosys plugin on top of the [usual requirements](../README.md), since the design is VHDL.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
