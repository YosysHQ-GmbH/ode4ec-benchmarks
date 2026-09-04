# fft64

[r22sdf](https://github.com/nanamake/r22sdf)'s 64-point pipelined FFT using a
Radix-2² Single-path Delay Feedback (SDF) architecture — the same core wrapped by
[yosys-perf](https://github.com/YosysHQ/yosys-perf)'s `fft64` benchmark
(`scripts/fft.py`, `hierarchy -top FFT -chparam WIDTH ...`). Top module `FFT`.

`find_max_parameter.py` sweeps the datapath `WIDTH` parameter, finding the largest
value that still formally verifies within 300s — plain Yosys synth and an ORFS
variant, each checked as MI and IA (see [top-level README](../README.md)).

Note: the vendored `Twiddle64.v` twiddle-factor table is hardcoded to 16-bit
constants regardless of `WIDTH` (an upstream limitation, not something this harness
works around) — at `WIDTH != 16` the design no longer computes a numerically
meaningful FFT, but this doesn't affect what's being checked here: equivalence
between the RTL and its synthesized netlist at whatever `WIDTH` is swept to, not
functional correctness of the FFT itself.

## BMC depth

`tasks.sby.in` here overrides the shared BMC `depth` to 155 (the shared default is
20). FFT64's pipeline needs ~147 cycles before `do_en` can go high at all —
confirmed via a standalone BMC check on `gold_top` alone, unrolled to depth 150;
the vendor's own "71 clock cycles" comment in `FFT64.v` undercounts this, likely
because it assumes a specific continuous `di_en` streaming pattern rather than the
fully free inputs a formal check explores. Below depth 155 every BMC-mode MI
(I/O-only) check is vacuous: `do_en`/`do_re`/`do_im` just sit at their reset value
for the whole window, identically in gold and gate, so a "PASS" proves nothing
about real datapath equivalence. 155 leaves a small margin past the earliest
possible `do_en` pulse. This is specific to FFT64's latency — the other benchmarks
have far shorter pipelines and use the depth-20 default.

## Running

    uv run find_max_parameter.py

or `make fft64` from the parent folder.

Results go to `run/` alongside the usual `results.csv`/`.parquet` and plots.
