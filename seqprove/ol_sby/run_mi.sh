#!/usr/bin/env bash
# usage: run_mi.sh <benchmark> <run>  -> plain miter (the run's own miter.sby), timeouts 30 -> 300s,
# only abc-pdr and aiger-suprove (aiger-rIC3 dropped after pl_stage S479: ~25GB, OOM). Appends to results_mi.csv
set -uo pipefail
export PATH=$HOME/Yosys/oss-cad-suite/bin:$PATH
B=$1; R=$2; HERE=$(cd "$(dirname "$0")" && pwd); FC=$HOME/Work/ode4ec-benchmarks/internal_assertions_frontier_checks
SRC=$FC/$B/run/$R; OUT=$HERE/$B/$R; mkdir -p $OUT; cd $OUT
cp $SRC/{gold.il,gate.il,miter.v} .; ln -sfn $FC/sky130 sky130
sed -e 's/timeout [0-9]*$/timeout 300/' -e 's|^\.\./\.\./sky130$|sky130|' $SRC/miter.sby > mi.sby
one() { t=$1; s=$(date +%s); rm -rf mi_$t; timeout 400 nice -n 5 sby -f -d mi_$t mi.sby $t > /dev/null 2>&1
  r=$(ls mi_$t 2>/dev/null | grep -E '^(PASS|FAIL|TIMEOUT|ERROR|UNKNOWN)$' | head -1)
  echo "$B,$R,$t,prove,${r:-NORESULT},$(( $(date +%s)-s ))" | tee -a $HERE/results_mi.csv; }
for t in abc-pdr aiger-suprove; do  # aiger-rIC3 dropped: portfolio uses ~25GB (15 workers)
 one $t & done; wait
