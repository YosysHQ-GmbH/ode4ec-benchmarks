#!/usr/bin/env bash
# usage: run_sby.sh <ia|mi> engine...   -> the given benchmark engines in parallel (no clk2fflogic, 900 s timeout in the sby file)
export PATH=$HOME/Yosys/oss-cad-suite/bin:$PATH
v=$1; shift; cd "$(dirname "$0")"; out=sby_$v.csv; [ -f $out ] || echo "variant,engine,result,secs" > $out
one() { t=$1; s=$(date +%s%N); (cd $v && rm -rf run_$t && timeout 1000 sby -f -d run_$t noclk.sby $t >/dev/null 2>&1)
  e=$(python3 -c "print(round(($(date +%s%N)-$s)/1e9,1))")
  r=$(ls $v/run_$t 2>/dev/null | grep -E '^(PASS|FAIL|TIMEOUT|ERROR|UNKNOWN)$' | head -1); echo "$v,$t,${r:-NORESULT},$e" >> $out; }
for t in "$@"; do one $t & done
wait; echo "BATCH DONE $v $*"
