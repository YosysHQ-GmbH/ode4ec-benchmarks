# Third-party notices

This repository's own code (the Python files and the `design.toml` files) is licensed under the ISC License, see
[LICENSE](LICENSE).

The sources of most designs in `bench/designs/` (each design's `src/`, and `_lib/open-logic`) are vendored from
third-party open-source hardware projects and kept largely unmodified. Each vendored file keeps its original copyright
and license header, and that header is what applies to the file. This document is only an index; `licenses/` holds the
full text of each license.

| Design(s) | Project | Upstream | License |
|---|---|---|---|
| `ol_arb_prio`, `ol_arb_rr`, `ol_arb_wrr`, `ol_dyn_sft`, `ol_fifo_async`, `ol_fifo_sync`, `ol_pl_stage`, `ol_ram_sdp`, `ol_ram_sp`, `ol_tdm`, `ol_wconv_n2m`, `ol_wconv_n2xn`, `ol_wconv_xn2n` | open-logic | https://github.com/open-logic/open-logic | [PSI HDL Library License 1.0](licenses/PSI-HDL-Library-License-1.0.txt) (based on LGPL-2.1, with an exception for FPGA bitstreams and other binaries) |
| `picorv32` | picorv32 | https://github.com/YosysHQ/picorv32 | [ISC](licenses/ISC.txt) |
| `serv`, `corescore` | SERV | https://github.com/olofk/serv | [ISC](licenses/ISC.txt) |
| `neorv32` | NEORV32 | https://github.com/stnolting/neorv32 | [BSD-3-Clause](licenses/BSD-3-Clause.txt) |
| `skordal_potato` | Potato Processor | https://github.com/skordal/potato | [BSD-3-Clause](licenses/BSD-3-Clause.txt) |
| `secworks_sha256`, `secworks_aes`, `secworks_poly1305`, `secworks_chacha` | secworks cores | https://github.com/secworks | [BSD-2-Clause](licenses/BSD-2-Clause.txt) |
| `htl32imc` | HTL32IMC | https://github.com/htminuslab/HTL32IMC | [MIT](licenses/MIT.txt) |
| `corescore` (wrapper RTL: `base.v`, `emitter*.v`, `axis2wb.v`, `wb2axis.v`, `corescore_de10_nano.v`, `de0_nano_clock_gen.v`) | corescore | https://github.com/olofk/corescore | [Apache-2.0](licenses/Apache-2.0.txt) |
| `corescore` (`verilog-axis_0-r3/`) | verilog-axis | https://github.com/alexforencich/verilog-axis | [MIT](licenses/MIT.txt) |
| `bench/platforms/sky130hd` | SkyWater Open Source PDK (`sky130_fd_sc_hd`) | https://github.com/google/skywater-pdk | [Apache-2.0](licenses/Apache-2.0.txt) |
| `fft64` | r22sdf (pipelined FFT), also used by the `fft64`/`fft1024` benchmarks of [yosys-perf](https://github.com/YosysHQ/yosys-perf) | https://github.com/nanamake/r22sdf | [MIT](licenses/MIT.txt) |
| `jpeg` | JPEG Encoder Unit (OpenCores "Video Compression Systems Project"), also used by OpenROAD-flow-scripts' `flow/designs/src/jpeg/` and by the `scripts/jpeg.py` benchmark of [yosys-perf](https://github.com/YosysHQ/yosys-perf) | https://opencores.org/projects/video_systems | [Permissive "as-is" notice](licenses/OpenCores-JPEG-Encoder.txt) (ASICs World Services and Richard Herveille) |
| `cva6` (git submodule, not vendored, see below) | CVA6 | https://github.com/openhwgroup/cva6 | Solderpad Hardware License (derived from Apache-2.0) |

`xorgrid` (`xorgrid.py`) and corescore's generator `gen.py` were written for this project.

## Not vendored

`bench/designs/cva6/src/cva6` is a git submodule of https://github.com/openhwgroup/cva6, and `bench/orfs` is a local
clone of https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts that git ignores. Neither is part of this
repository's history. `bench/designs/cva6/Flist_formal.cva6` is cva6's `core/Flist.cva6` without the cvxif_example
files. The build and run scripts of OpenROAD-flow-scripts are BSD-3-Clause (see its `LICENSE_BUILD_RUN_SCRIPTS`), and
the OpenROAD tools and PDKs it pulls in have their own licenses.

## LGPL note

The license of open-logic is based on the LGPL. Its files are used unmodified, with the copyright and license headers
as distributed upstream, and the full license text is in `licenses/`.
