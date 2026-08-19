# ode4ec-benchmarks

Benchmarks for studying **internal assertions** in formal equivalence checking: does asserting that internal (non-I/O) registers match between RTL and a synthesized gate netlist — not just the outputs — help `sby`/Yosys prove equivalence faster or on bigger designs? Two suites live here, each answering that from a different angle:

- [`internal_assertions/`](internal_assertions/README.md) — fixed-size correctness suite. Checks a large set of real IP cores (picorv32, cva6, serv, various open-logic/secworks blocks, ...) with both plain and internal-asserts miters, plus mutation testing to confirm the checks actually catch injected bugs.
- [`internal_assertions_frontier_checks/`](internal_assertions_frontier_checks/README.md) — scaling suite. Binary-searches a size parameter per design (core count, bus width, grid size, ...) to find the largest value that still formally verifies within a timeout, comparing that "frontier" with a plain miter vs. with internal asserts.

Both compare synthesis from plain Yosys against a full [OpenROAD-flow-scripts](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts) place-and-route flow, and each has its own `Makefile` and README with setup/run details.
