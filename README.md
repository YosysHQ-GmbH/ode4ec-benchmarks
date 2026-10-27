# ode4ec-benchmarks

Benchmarks for equivalence checking of RTL against its synthesized gate netlist with eqy.

The suite is in [`bench/`](bench/README.md). Each design is built at its parameter points by two gate flows (Yosys
and OpenROAD-flow-scripts synthesis, sky130hd cells) and checked with eqy and a plain sby miter, with an output cover
and gate mutants as non-vacuity evidence. `kpi.py` scores each check (time to solve, size scaling). Setup and usage
are in its README.

Needs OSS CAD Suite (yosys with the slang and ghdl plugins, eqy, sby) and `uv` for the generated designs.
Third-party sources and their licenses: [NOTICE.md](NOTICE.md).
