# ol_arb_prio

[open-logic](https://github.com/open-logic/open-logic)'s `olo_base_arb_prio` — a priority arbiter in VHDL, elaborated via Yosys's `ghdl` plugin. Two generics, `Width_g` and `Latency_g`, are swept independently.

`find_max_parameter.py` runs both sweeps (width fixed-latency, latency fixed-width), finding the largest value that still formally verifies within 60s — plain Yosys synth and an ORFS variant, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make ol_arb_prio` from the parent folder. Needs the `ghdl` Yosys plugin on top of the [usual requirements](../README.md), since the design is VHDL.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
