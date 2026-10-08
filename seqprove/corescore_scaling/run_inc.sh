#!/usr/bin/env bash
# usage: run_inc.sh N solver [--declare]   -> incremental proof on c<N>/ia, appends to c<N>/inc.csv
export PATH=$HOME/Yosys/oss-cad-suite/bin:$PATH
N=$1; solver=$2; extra=${3:-}; D=$(cd "$(dirname "$0")" && pwd); SP=$D/../xorgrid_incremental/seq_prove.py
cd $D/c$N/ia; s=$(date +%s); timeout 1000 python3 $SP miter_sync.smt2 --k 2 --solver $solver $extra --src asserts.vh > inc_$solver.log 2>&1; rc=$?
e=$(( $(date +%s)-s )); r=$(grep -E '^PROVEN' inc_$solver.log | sed -E 's/PROVEN ([0-9]+\/[0-9]+).*/\1/'); n=$(grep -c 'step case fails\|FALSIFIED' inc_$solver.log)
echo "$solver,${r:-NOFINISH(rc=$rc;checked=$n)},$e" >> ../inc.csv
