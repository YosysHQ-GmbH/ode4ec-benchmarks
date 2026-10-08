#!/usr/bin/env bash
# usage: run_size3.sh N   (after setup_case.sh N and the ic3 file prep)
export PATH=$HOME/Yosys/oss-cad-suite/bin:$PATH
N=$1; D=$(cd "$(dirname "$0")" && pwd); cd $D/c$N
E5="abc-pdr aiger-suprove btor-btormc smtbmc-bitwuzla smtbmc-z3"
[ -f inc.csv ] || echo "solver,result,secs" > inc.csv
./run_sby.sh ia $E5 & $D/run_inc.sh $N yices & wait
./run_sby.sh mi $E5 & $D/run_inc.sh $N boolector --declare & wait
./run_sby_ic3.sh ia aiger-rIC3 btor-rIC3 & ./run_sby_ic3.sh mi aiger-rIC3 btor-rIC3 & wait
echo "SIZE DONE C$N"
