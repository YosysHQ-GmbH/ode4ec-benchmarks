# ol_wconv_xn2n

[open-logic](https://github.com/open-logic/open-logic)'s `olo_base_wconv_xn2n` — a width converter from an integer multiple of `OutWidth_g` bits, `InWidth_g`, down to `OutWidth_g` bits, in VHDL, elaborated via Yosys's `ghdl` plugin. The VHDL entity asserts `InWidth_g` is an exact multiple of `OutWidth_g` (the mirror image of [ol_wconv_n2xn](../ol_wconv_n2xn)'s constraint), so `InWidth_g`/`OutWidth_g` cannot be swept independently.

`find_max_parameter.py` sweeps two axes that always keep the ratio integral:
- **Ratio Scaling**: `OutWidth_g` fixed, `InWidth_g = n * OutWidth_g` swept over the ratio `n`.
- **Width Scaling**: the ratio fixed, `OutWidth_g = n` swept and `InWidth_g = ratio * n` recomputed alongside it.

Each finds the largest value that still formally verifies within 60s — plain Yosys synth and an ORFS variant, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make ol_wconv_xn2n` from the parent folder. Needs the `ghdl` Yosys plugin on top of the [usual requirements](../README.md), since the design is VHDL.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
