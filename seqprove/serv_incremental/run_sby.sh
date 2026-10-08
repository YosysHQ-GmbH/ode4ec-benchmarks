#!/usr/bin/env bash
# usage: run_sby.sh  -> runs the 4 benchmark engines for MI and IA (no clk2fflogic) in parallel, 1800 s timeout each
export PATH=$HOME/Yosys/oss-cad-suite/bin:$PATH
cd "$(dirname "$0")"; echo "variant,task,result,secs" > sby_serv.csv
one() { v=$1; t=$2; f=$([ $v = mi ] && echo noclk_mi.sby || echo noclk_ia.sby)
  s=$(date +%s%N); (cd $v && rm -rf run_$t && timeout 1900 sby -f -d run_$t $f $t >/dev/null 2>&1)
  e=$(python3 -c "print(round(($(date +%s%N)-$s)/1e9,1))")
  r=$(ls $v/run_$t 2>/dev/null | grep -E '^(PASS|FAIL|TIMEOUT|ERROR|UNKNOWN)$' | head -1); echo "$v,$t,${r:-NORESULT},$e" >> sby_serv.csv; }
for v in mi ia; do for t in task_abc task_aiger task_bitwuzla task_btor; do one $v $t & done; done
wait; echo ALL DONE
