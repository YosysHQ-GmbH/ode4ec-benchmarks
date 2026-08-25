# ol_arb_wrr

[open-logic](https://github.com/open-logic/open-logic)'s `olo_base_arb_wrr` — a weighted round-robin arbiter in VHDL, elaborated via Yosys's `ghdl` plugin. Two generics, `GrantWidth_g` (number of requesters) and `WeightWidth_g` (bits per weight), are swept independently. The third generic, `Latency_g`, is a VHDL `natural range 0 to 1` (only two legal values, not a scalable size) and is fixed to `1` for all sweeps rather than exposed as a sweep axis, mirroring how [ol_pl_stage](../ol_pl_stage)'s `UseReady_g` is fixed.

`find_max_parameter.py` runs both sweeps (grant-count fixed-weight-width, weight-width fixed-grant-count), finding the largest value that still formally verifies within 60s — plain Yosys synth and an ORFS variant, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make ol_arb_wrr` from the parent folder. Needs the `ghdl` Yosys plugin on top of the [usual requirements](../README.md), since the design is VHDL.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
