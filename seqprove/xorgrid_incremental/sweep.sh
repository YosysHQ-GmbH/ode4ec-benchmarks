#!/usr/bin/env bash
# usage: sweep.sh <solver> <timeout_s> W...   -> appends to sweep_<solver>.csv; stops at the first timeout
solver=$1; to=$2; shift 2
RUN=~/Work/ode4ec-benchmarks/internal_assertions_frontier_checks/xorgrid/run
out=sweep_$solver.csv; [ -f $out ] || echo "W,solver,k,asserts,result,secs" > $out
for w in "$@"; do
  d=$RUN/I16_O16_C16_W${w}_H${w}_F8_N6_D4_S0_T600
  [ -f $d/miter.v ] || { echo "W$w: no inputs in run dir, skipped"; continue; }
  [ -f case_w$w/miter_sync.smt2 ] || ./build_case.sh $d case_w$w >/dev/null
  s=$(date +%s%N)
  log=$(timeout $to python3 seq_prove.py case_w$w/miter_sync.smt2 --k 2 --solver $solver $([ $solver = boolector ] && echo --declare) --src case_w$w/asserts.vh 2>&1); rc=$?
  e=$(python3 -c "print(round(($(date +%s%N)-$s)/1e9,1))")
  n=$(grep -c 'yosys-smt2-assert' case_w$w/miter_sync.smt2)
  if [ $rc -eq 124 ]; then echo "$w,$solver,2,$n,TIMEOUT,$e" >> $out; echo "W$w TIMEOUT after ${e}s"; break; fi
  res=$(grep -E '^PROVEN' <<<"$log" | sed -E 's/PROVEN ([0-9]+)\/([0-9]+).*/\1\/\2/')
  [ -n "$res" ] || { echo "W$w ERROR: $(tail -1 <<<"$log")"; echo "$w,$solver,2,$n,ERROR,$e" >> $out; break; }
  echo "$w,$solver,2,$n,PROVEN $res,$e" >> $out; echo "W$w PROVEN $res in ${e}s"
done
