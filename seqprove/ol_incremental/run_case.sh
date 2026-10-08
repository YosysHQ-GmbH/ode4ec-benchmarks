#!/usr/bin/env bash
# usage: run_case.sh <benchmark> <run name> <old|new> [timeout_s]
#   old: the run's own asserts.vh;  new: regenerated (match_gate_wires + const_candidates)
# Builds a single-clock model (no clk2fflogic, asserts in always @*) and runs seq_prove (yices, k=2, --chunk 16 --model).
# Appends bench,run,variant,asserts,result,secs to results.csv
set -uo pipefail
export PATH=$HOME/Yosys/oss-cad-suite/bin:$PATH
B=$1; R=$2; V=$3; TO=${4:-300}
HERE=$(cd "$(dirname "$0")" && pwd); FC=$HOME/Work/ode4ec-benchmarks/internal_assertions_frontier_checks
SRC=$FC/$B/run/$R; OUT=$HERE/$B/$R/$V; mkdir -p $OUT; cd $OUT
cp $SRC/{gold.il,gate.il,miter.v} .; ln -sfn $FC/sky130 sky130
if [ $V = old ]; then cp $SRC/{asserts.vh,decls.vh,expose.ys,ports_a.vh,ports_b.vh} .
else python3 -c "
import sys; from pathlib import Path as P
sys.path.insert(0, '$FC')
from _common.generate_internal_asserts import generate_assert_files as g
g(P('gold.il'),P('gate.il'),P('expose.ys'),P('decls.vh'),P('ports_a.vh'),P('ports_b.vh'),P('asserts.vh'), match_gate_wires=True, const_candidates=True)"
fi
sed -E 's/always @\(posedge [A-Za-z_]+\) begin/always @* begin/' miter.v > miter_comb.v
{ sed -n '/^\[script\]/,/^\[files\]/p' $SRC/miter_extra_asserts.sby | sed '1d;$d' | grep -v '^clk2fflogic' | sed 's/ miter\.v / miter_comb.v /'
  echo "prep -top miter"; echo "dffunmap"; echo "write_smt2 -wires miter_comb.smt2"; } > build_comb.ys
yosys -q -l build.log build_comb.ys > /dev/null 2>&1 || { echo "$B,$R,$V,,BUILD_ERROR,0" >> $HERE/results.csv; exit 1; }
n=$(grep -c yosys-smt2-assert miter_comb.smt2)
s=$(date +%s)
timeout $TO python3 -u $HERE/../xorgrid_incremental/seq_prove.py miter_comb.smt2 --k 2 --solver yices --chunk 16 --model --src asserts.vh > seq.log 2>&1 </dev/null; rc=$?
e=$(( $(date +%s)-s ))
r=$(grep -E '^PROVEN' seq.log | sed -E 's/PROVEN ([0-9]+\/[0-9]+).*/\1/')
[ $rc -eq 124 ] && r=TIMEOUT; [ -n "$r" ] || r="ERROR"
echo "$B,$R,$V,$n,$r,$e" >> $HERE/results.csv; echo "$B $R $V: $n asserts -> $r in ${e}s"
