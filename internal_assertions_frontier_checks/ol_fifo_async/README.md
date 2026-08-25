# ol_fifo_async

[open-logic](https://github.com/open-logic/open-logic)'s `olo_base_fifo_async` — a dual-clock-domain (asynchronous) FIFO in VHDL, elaborated via Yosys's `ghdl` plugin. Two generics, `Depth_g` and `Width_g`, are swept independently; the almost-full/almost-empty/optimization-mode generics stay at their VHDL defaults, matching the original benchmark leaving `In_AlmFull`/`In_AlmEmpty`/`Out_AlmFull`/`Out_AlmEmpty` unconnected.

Unlike every other benchmark in this suite, this design genuinely has two independent clock/reset domains (`In_Clk`/`In_Rst` and `Out_Clk`/`Out_Rst`). The miter ports both `fminit -seq In_Rst 1,1,0 -posedge In_Clk` and `fminit -seq Out_Rst 1,1,0 -posedge Out_Clk` (both accepted together by `sby`/yosys — confirmed by the original `internal_assertions/ol_fifo_async` benchmark's own `custom_miter.sby.in`), and each domain gets its own settle-cycle counter (`in_checks_ok`/`out_checks_ok`) gating when assertions activate on that side, ported verbatim from the original miter.

`find_max_parameter.py` runs both sweeps (depth fixed-width, width fixed-depth), finding the largest value that still formally verifies within 60s — plain Yosys synth and an ORFS variant, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make ol_fifo_async` from the parent folder. Needs the `ghdl` Yosys plugin on top of the [usual requirements](../README.md), since the design is VHDL.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
