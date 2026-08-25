# ol_ram_sdp

[open-logic](https://github.com/open-logic/open-logic)'s `olo_base_ram_sdp` — a simple dual-port RAM (separate write and read address/enable, one data width) in VHDL, elaborated via Yosys's `ghdl` plugin. Two generics, `Depth_g` and `Width_g`, are swept independently; all other generics (`IsAsync_g`, `RdLatency_g`, `RamStyle_g`, `RamBehavior_g`, `UseByteEnable_g`, init settings) are left at their VHDL defaults — in particular `IsAsync_g=false`, so the design stays single-clock (the separate `Rd_Clk` port is unused, matching the original benchmark's miter).

`find_max_parameter.py` runs both sweeps (depth fixed-width, width fixed-depth), finding the largest value that still formally verifies within 60s — plain Yosys synth and an ORFS variant, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make ol_ram_sdp` from the parent folder. Needs the `ghdl` Yosys plugin on top of the [usual requirements](../README.md), since the design is VHDL.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
