# xorgrid

`xorgrid.py` generates a synthetic `W`×`H` grid of tiles, each an `N`-bit register whose next state XORs bits routed in from nearby tiles or primary inputs, picked by global control bits. 

`find_max_parameter.py` runs three sweeps (grid size, control-bit count, max routing distance) plus their ORFS variants, finding the largest value that still formally verifies within 600s, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make xorgrid` from the parent folder. No extra tools beyond the [usual requirements](../README.md) — `xorgrid.py` runs self-contained via `uv`.

Results go to `run/` alongside the usual `results.csv` and plots.
