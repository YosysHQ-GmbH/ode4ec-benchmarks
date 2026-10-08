#!/usr/bin/env bash
# usage: run_case.sh <benchmark> <run>   -> sby IA run with the regenerated asserts (../ol_incremental/<b>/<r>/new),
# the run's own sby file (clocked asserts, clk2fflogic), timeouts 30 -> 300s; all engines in parallel.
# Appends bench,run,engine,mode,result,secs to results.csv
set -uo pipefail
export PATH=$HOME/Yosys/oss-cad-suite/bin:$PATH
B=$1; R=$2; HERE=$(cd "$(dirname "$0")" && pwd); FC=$HOME/Work/ode4ec-benchmarks/internal_assertions_frontier_checks
SRC=$FC/$B/run/$R; NEW=$HERE/../ol_incremental/$B/$R/new; OUT=$HERE/$B/$R; mkdir -p $OUT; cd $OUT
cp $SRC/{gold.il,gate.il,miter.v} .; cp $NEW/{asserts.vh,decls.vh,expose.ys,ports_a.vh,ports_b.vh} .
ln -sfn $FC/sky130 sky130
sed -e 's/timeout 30$/timeout 300/' -e 's|^\.\./\.\./sky130$|sky130|' $SRC/miter_extra_asserts.sby > ia.sby
tasks=$(sed -n '/^\[tasks\]/,/^\[/p' ia.sby | grep -vE '^\[|^#|^\s*$')
one() { t=$1; mode=$(grep -m1 "^$t: mode" ia.sby | awk '{print $3}'); s=$(date +%s)
  rm -rf ia_$t; timeout 400 sby -f -d ia_$t ia.sby $t > /dev/null 2>&1
  r=$(ls ia_$t 2>/dev/null | grep -E '^(PASS|FAIL|TIMEOUT|ERROR|UNKNOWN)$' | head -1)
  echo "$B,$R,$t,$mode,${r:-NORESULT},$(( $(date +%s)-s ))" | tee -a $HERE/results.csv; }
for t in $tasks; do one $t & done; wait
