# ol_wconv_n2m

[open-logic](https://github.com/open-logic/open-logic)'s `olo_base_wconv_n2m` — a general width converter between arbitrary `InWidth_g` and `OutWidth_g` bit widths (no integer-ratio constraint, unlike [ol_wconv_n2xn](../ol_wconv_n2xn)/[ol_wconv_xn2n](../ol_wconv_xn2n)), in VHDL, elaborated via Yosys's `ghdl` plugin. `UseBe_g` stays at its VHDL default (`false`); `InWidth_g`/`OutWidth_g` are swept independently.

`find_max_parameter.py` runs both sweeps (input-width fixed-output-width, output-width fixed-input-width), finding the largest value that still formally verifies within 60s — plain Yosys synth and an ORFS variant, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make ol_wconv_n2m` from the parent folder. Needs the `ghdl` Yosys plugin on top of the [usual requirements](../README.md), since the design is VHDL.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
