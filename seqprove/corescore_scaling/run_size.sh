#!/usr/bin/env bash
# usage: run_size.sh N   (after setup_case.sh N)
export PATH=$HOME/Yosys/oss-cad-suite/bin:$PATH
N=$1; cd "$(dirname "$0")/c$N"; SP=../../xorgrid_incremental/seq_prove.py
inc() { solver=$1; extra=$2; s=$(date +%s)
  (cd ia && timeout 1000 python3 $SP miter_sync.smt2 --k 2 --solver $solver $extra --src asserts.vh > inc_$solver.log 2>&1); rc=$?
  e=$(( $(date +%s)-s )); r=$(grep -E '^PROVEN' ia/inc_$solver.log | sed -E 's/PROVEN ([0-9]+\/[0-9]+).*/\1/'); 
  n=$(grep -c 'step case fails\|FALSIFIED' ia/inc_$solver.log)
  echo "$solver,${r:-NOFINISH(rc=$rc;retracted_so_far=$n)},$e" >> inc.csv; }
[ -f inc.csv ] || echo "solver,result,secs" > inc.csv
E5="abc-pdr aiger-suprove btor-btormc smtbmc-bitwuzla smtbmc-z3"
./run_sby.sh ia $E5 & inc yices "" & wait
./run_sby.sh mi $E5 & inc boolector --declare & wait
./run_sby.sh ia aiger-rIC3 & ./run_sby.sh mi aiger-rIC3 & wait
./run_sby.sh ia btor-rIC3 & ./run_sby.sh mi btor-rIC3 & wait
echo "SIZE DONE C$N"
