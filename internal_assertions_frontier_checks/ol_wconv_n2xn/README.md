# ol_wconv_n2xn

[open-logic](https://github.com/open-logic/open-logic)'s `olo_base_wconv_n2xn` — a width converter from `InWidth_g` bits to an integer multiple of it, `OutWidth_g` bits, in VHDL, elaborated via Yosys's `ghdl` plugin. The VHDL entity asserts `OutWidth_g` is an exact multiple of `InWidth_g` (and `>=` it), so `InWidth_g`/`OutWidth_g` cannot be swept independently like a normal two-generic design.

`find_max_parameter.py` instead sweeps two axes that always keep the ratio integral:
- **Ratio Scaling**: `InWidth_g` fixed, `OutWidth_g = n * InWidth_g` swept over the ratio `n`.
- **Width Scaling**: the ratio fixed, `InWidth_g = n` swept and `OutWidth_g = ratio * n` recomputed alongside it.

Each finds the largest value that still formally verifies within 60s — plain Yosys synth and an ORFS variant, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make ol_wconv_n2xn` from the parent folder. Needs the `ghdl` Yosys plugin on top of the [usual requirements](../README.md), since the design is VHDL.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
