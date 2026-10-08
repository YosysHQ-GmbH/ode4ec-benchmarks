#!/usr/bin/env bash
# usage: setup_case.sh N   -> c<N>/{ia,mi} with noclk sby files, IA smt2 (single-clock model), run_sby.sh
set -euo pipefail
export PATH=$HOME/Yosys/oss-cad-suite/bin:$PATH
N=$1; B=~/Work/ode4ec-benchmarks; SRC=$B/internal_assertions_frontier_checks/corescore/run/C${N}_T900
W=$(cd "$(dirname "$0")" && pwd)/c$N; mkdir -p $W/ia $W/mi
for d in ia mi; do cp $SRC/{gold.il,gate.il,miter.v} $W/$d/; ln -sfn $B/internal_assertions_frontier_checks/sky130 $W/$d/sky130; done
cp $SRC/{asserts.vh,decls.vh,expose.ys,ports_a.vh,ports_b.vh} $W/ia/
grep -v '^clk2fflogic' $SRC/miter_extra_asserts.sby | sed 's|^\.\./\.\./sky130$|sky130|' > $W/ia/noclk.sby
grep -v '^clk2fflogic' $SRC/miter.sby | sed 's|^\.\./\.\./sky130$|sky130|' > $W/mi/noclk.sby
cp ../corescore_c8/run_sby.sh $W/run_sby.sh 2>/dev/null || cp "$(dirname "$0")/../corescore_c8/run_sby.sh" $W/run_sby.sh
cp "$(dirname "$0")/../corescore_c8/ia/build_sync.ys" $W/ia/build_sync.ys
(cd $W/ia && yosys -q -l build.log build_sync.ys)
echo "C$N: cells=$(grep -E ' cells$' $SRC/stat.txt 2>/dev/null | awk '{print $1}') smt2=$(du -h $W/ia/miter_sync.smt2 | cut -f1) asserts=$(grep -c yosys-smt2-assert $W/ia/miter_sync.smt2) regs=$(grep -c yosys-smt2-register $W/ia/miter_sync.smt2)"
