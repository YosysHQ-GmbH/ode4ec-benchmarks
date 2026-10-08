#!/usr/bin/env bash
# usage: build_case.sh <benchmark run dir, e.g. .../xorgrid/run/I16_O16_C16_W8_H8_...> <out dir>
# Copies the inputs of the IA miter and writes <out>/miter_sync.smt2 (single-clock model, no clk2fflogic).
set -euo pipefail
SRC=$(readlink -f "$1"); OUT=$2; mkdir -p "$OUT"
name=$(basename "$SRC")
I=$(sed -E 's/.*I([0-9]+)_O.*/\1/' <<<"$name"); O=$(sed -E 's/.*_O([0-9]+)_C.*/\1/' <<<"$name"); C=$(sed -E 's/.*_C([0-9]+)_W.*/\1/' <<<"$name")
for f in miter.v asserts.vh decls.vh expose.ys ports_a.vh ports_b.vh gold.il gate.il; do cp "$SRC/$f" "$OUT/"; done
ln -sfn "$SRC/../../sky130" "$OUT/sky130"
cat > "$OUT/build_sync.ys" <<EOT
read_rtlil gold.il
read_liberty -ignore_miss_func sky130/sky130_fd_sc_hd__tt_025C_1v80.lib
read_rtlil gate.il
script expose.ys
plugin -i slang
read_slang --top miter miter.v -D INTERNAL_ASSERTS -G I=$I -G O=$O -G C=$C
hierarchy -top miter
flatten
hierarchy -top miter
setundef -zero
setundef -undriven -init -zero
async2sync
prep -top miter
dffunmap
write_smt2 -wires miter_sync.smt2
EOT
(cd "$OUT" && yosys -q build_sync.ys)
grep -c yosys-smt2-assert "$OUT/miter_sync.smt2"
