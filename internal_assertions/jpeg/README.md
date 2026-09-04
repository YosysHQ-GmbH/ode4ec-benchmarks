# Summary

JPEG Encoder Unit — a DCT/quantization/run-length-encoding core from the OpenCores
"Video Compression Systems Project". This is the same core wrapped by both
OpenROAD-flow-scripts' `flow/designs/src/jpeg/` and
[yosys-perf](https://github.com/YosysHQ/yosys-perf)'s `scripts/jpeg.py` benchmark
(`jpeg`), which simply points Yosys at this source tree with
`hierarchy -top jpeg_encoder`.

# Source

Vendored from `internal_assertions/orfs/flow/designs/src/jpeg/` (OpenROAD-flow-scripts'
local copy), originally downloaded from
https://opencores.org/projects/video_systems on 8/8/2019. See
[`../../licenses/OpenCores-JPEG-Encoder.txt`](../../licenses/OpenCores-JPEG-Encoder.txt)
for the license.

Top module: `jpeg_encoder`.
