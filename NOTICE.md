# Third-party notices

This repository's own benchmark harness (Makefiles, Python, Tcl, and SBY/EQY
files) is licensed under the ISC License — see [LICENSE](LICENSE).

Several benchmark designs under `internal_assertions/` and
`internal_assertions_frontier_checks/` are vendored source files from
third-party open-source hardware projects, kept largely unmodified. Each
vendored file retains its original copyright/license header — those headers
are authoritative for that file. This document is a summary index, and
`licenses/` contains the full text of each license involved.

| Suite director(ies) | Project | Upstream | License |
|---|---|---|---|
| `ol_arb_prio`, `ol_arb_rr`, `ol_arb_wrr`, `ol_dyn_sft`, `ol_fifo_async`, `ol_fifo_sync`, `ol_pl_stage`, `ol_ram_sdp`, `ol_ram_sp`, `ol_tdm`, `ol_wconv_n2m`, `ol_wconv_n2xn`, `ol_wconv_xn2n` | open-logic | https://github.com/open-logic/open-logic | PSI HDL Library License 1.0 (LGPL-2.1-based, with an exception for FPGA-bitstream/binary use) — [licenses/PSI-HDL-Library-License-1.0.txt](licenses/PSI-HDL-Library-License-1.0.txt) |
| `picorv32` | picorv32 | https://github.com/YosysHQ/picorv32 | ISC — [licenses/ISC.txt](licenses/ISC.txt) |
| `serv` (both suites), `corescore` | SERV | https://github.com/olofk/serv | ISC — [licenses/ISC.txt](licenses/ISC.txt) |
| `neorv32` | NEORV32 | https://github.com/stnolting/neorv32 | BSD-3-Clause — [licenses/BSD-3-Clause.txt](licenses/BSD-3-Clause.txt) |
| `skordal_potato` | Potato Processor | https://github.com/skordal/potato | BSD-3-Clause — [licenses/BSD-3-Clause.txt](licenses/BSD-3-Clause.txt) |
| `secworks_sha256`, `secworks_aes`, `secworks_poly1305`, `secworks_chacha` | secworks cores | https://github.com/secworks | BSD-2-Clause — [licenses/BSD-2-Clause.txt](licenses/BSD-2-Clause.txt) |
| `htl32imc` | HTL32IMC | https://github.com/htminuslab/HTL32IMC | MIT — [licenses/MIT.txt](licenses/MIT.txt) |
| `dblclockfft` | dblclockfft (pipelined FFT) | https://github.com/ZipCPU/dblclockfft | LGPL-3.0 (or later) — [licenses/LGPL-3.0.txt](licenses/LGPL-3.0.txt) |
| `corescore` (wrapper RTL: `base.v`, `emitter*.v`, `axis2wb.v`, `wb2axis.v`, `corescore_de10_nano.v`, `de0_nano_clock_gen.v`) | corescore | https://github.com/olofk/corescore | Apache-2.0 — [licenses/Apache-2.0.txt](licenses/Apache-2.0.txt) |
| `sky130` (both suites) | SkyWater Open Source PDK (`sky130_fd_sc_hd`) | https://github.com/google/skywater-pdk | Apache-2.0 — [licenses/Apache-2.0.txt](licenses/Apache-2.0.txt) |
| `cva6` (referenced, not vendored — see note below) | CVA6 | https://github.com/openhwgroup/cva6 | Solderpad Hardware License (Apache-2.0-derived) |

`xorgrid` (frontier suite) is fully original — a synthetic design generator
written for this project, with no third-party source.

## Not vendored / not part of this repository's history

`cva6/src/cva6` (under `internal_assertions/`) and the `orfs/` directories
(full clones of https://github.com/openhwgroup/cva6 and
https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts, respectively)
are external tool/design dependencies that contributors clone locally to run
the benchmarks. They are intentionally excluded via `.gitignore` and are
never committed to this repository — only the small original glue files this
project writes to drive them (e.g. `openroad/*.tcl`, `openroad/*.sdc`,
`openroad/*.mk.in`) are tracked. OpenROAD-flow-scripts' own build/run scripts
are BSD-3-Clause (see its `LICENSE_BUILD_RUN_SCRIPTS`); the OpenROAD tools
and PDKs it in turn pulls in carry their own separate licenses.

## LGPL note

Two vendored components (open-logic and dblclockfft) are LGPL-derived. All
files from these projects are used verbatim (unmodified) in this repository;
per-file copyright/license headers are preserved as distributed upstream, and
the full license texts are included in `licenses/`.
