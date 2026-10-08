#!/usr/bin/env bash
# Rerun the benchmark's plain (MI) miter through sby WITHOUT clk2fflogic (noclk_mi.sby), one parallel lane per engine.
# Each lane walks W upward and stops at its first non-PASS. usage: sby_lanes.sh W...
export PATH=$HOME/Yosys/oss-cad-suite/bin:$PATH
HERE=$(cd "$(dirname "$0")" && pwd); cd "$HERE"
RUN=~/Work/ode4ec-benchmarks/internal_assertions_frontier_checks/xorgrid/run
ENGINES="abc-pdr aiger-suprove aiger-rIC3 btor-btormc btor-rIC3 smtbmc-bitwuzla smtbmc-z3"
Ws="$*"
for w in $Ws; do
  d=$RUN/I16_O16_C16_W${w}_H${w}_F8_N6_D4_S0_T600
  [ -f case_w$w/gold.il ] || { [ -f $d/miter.v ] && ./build_case.sh $d case_w$w >/dev/null; }
  [ -f case_w$w/gold.il ] && cp noclk_mi.sby case_w$w/noclk_mi.sby
done
lane() {
  eng=$1; out=sby_mi_noclk_$eng.csv; echo "W,engine,result,secs" > $out
  for w in $Ws; do
    [ -f case_w$w/noclk_mi.sby ] || continue
    rm -rf case_w$w/mi_noclk_$eng
    s=$(date +%s%N)
    (cd case_w$w && timeout 660 sby -f -d mi_noclk_$eng noclk_mi.sby $eng > /dev/null 2>&1)
    e=$(python3 -c "print(round(($(date +%s%N)-$s)/1e9,1))")
    res=$(cd case_w$w/mi_noclk_$eng 2>/dev/null && ls | grep -E '^(PASS|FAIL|TIMEOUT|ERROR|UNKNOWN)$' | head -1)
    [ -n "$res" ] || res=NORESULT
    echo "$w,$eng,$res,$e" >> $out
    [ "$res" = PASS ] || break
  done
}
for eng in $ENGINES; do lane $eng & done
wait
echo ALL DONE
