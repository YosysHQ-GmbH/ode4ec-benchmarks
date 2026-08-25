# ol_fifo_sync

[open-logic](https://github.com/open-logic/open-logic)'s `olo_base_fifo_sync` — a single-clock-domain FIFO in VHDL, elaborated via Yosys's `ghdl` plugin. Two generics, `Depth_g` and `Width_g`, are swept independently; the almost-full/almost-empty generics stay at their VHDL defaults (`AlmFullOn_g`/`AlmEmptyOn_g` = false), matching the original benchmark leaving `AlmFull`/`AlmEmpty` unconnected.

`find_max_parameter.py` runs both sweeps (depth fixed-width, width fixed-depth), finding the largest value that still formally verifies within 60s — plain Yosys synth and an ORFS variant, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make ol_fifo_sync` from the parent folder. Needs the `ghdl` Yosys plugin on top of the [usual requirements](../README.md), since the design is VHDL.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
