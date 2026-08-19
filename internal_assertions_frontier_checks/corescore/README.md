# corescore

`count` copies of the [SERV](https://github.com/olofk/serv) bit-serial RISC-V core wired through an AXI-Stream arbiter, assembled by [FuseSoC](https://fusesoc.readthedocs.io/). More cores = gnarlier arbitration logic to verify.

`find_max_parameter.py` sweeps `count` and finds the largest value that still formally verifies within 60s — plain Yosys synth and an ORFS variant, each checked as MI and IA (see [top-level README](../README.md)).

## Running

```
uv run find_max_parameter.py
```

or `make corescore` from the parent folder. Needs `fusesoc` on top of the [usual requirements](../README.md) — `find_max_parameter.py` calls it itself to generate each core count's RTL.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
