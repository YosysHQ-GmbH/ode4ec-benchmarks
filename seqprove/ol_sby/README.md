# sby rerun with the regenerated internal asserts (2026-09-25)

    ./run_case.sh <benchmark> <run>     # all 7 engines in parallel, appends to results.csv

Uses the run's own miter_extra_asserts.sby (clocked asserts, clk2fflogic, fminit reset) with the asserts from
../ol_incremental/<b>/<r>/new (fixed generator) and timeouts 30 -> 300s. One case at a time (7 engines).
A first attempt with two cases in parallel ran out of memory (results_oom.csv, run_oom.log: discard).
Only abc-pdr, aiger-suprove, aiger-rIC3 prove; the other 4 run `mode bmc` depth 20 and never finished in 300s.
OOM kills in the valid run: 3x btormc, 1x btor-rIC3 (BMC engines only, their ERRORs mean OOM).

sby: best prove engine, wall time incl. its model build. seq_prove: yosys build (build_times.csv, one at a time)
+ solve (../ol_incremental/results.csv; solve measured with 4 jobs in parallel), yices k=2 --chunk 16 --model.

| benchmark | run          | sby (300s)                     | seq_prove build+solve        |
|-----------|--------------|--------------------------------|------------------------------|
| fifo_sync | D4_W1589_T30 | PASS 161s (aiger-suprove)      | PASS 11+103=114s             |
| fifo_sync | D4_W1590_T30 | PASS 125s (aiger-suprove)      | PASS 11+109=120s             |
| fifo_sync | D4_W2048_T30 | PASS 236s (aiger-suprove)      | PASS 16+171=187s             |
| pl_stage  | W16_S479_T30 | TIMEOUT (all 3 prove engines)  | PASS 85+280=365s             |
| pl_stage  | W16_S480_T30 | TIMEOUT (all 3 prove engines)  | PASS 85+283=368s             |
| pl_stage  | W16_S512_T30 | TIMEOUT (all 3 prove engines)  | TIMEOUT (build 98s + >300s)  |
| ram_sdp   | D4_W3236_T30 | PASS 197s (aiger-suprove)      | TIMEOUT (build 32s + >300s)  |
| ram_sdp   | D4_W3237_T30 | PASS 190s (aiger-suprove)      | TIMEOUT (build 32s + >300s)  |
| ram_sdp   | D4_W4096_T30 | PASS 263s (aiger-suprove)      | TIMEOUT (build 48s + >300s)  |
| ram_sp    | D4_W3135_T30 | PASS 163s (aiger-suprove)      | TIMEOUT (build 36s + >300s)  |
| ram_sp    | D4_W3136_T30 | PASS 188s (aiger-suprove)      | TIMEOUT (build 36s + >300s)  |
| ram_sp    | D4_W4096_T30 | TIMEOUT (all 3 prove engines)  | TIMEOUT (build 56s + >300s)  |

- With the fixed asserts sby proves sizes it failed before at 30s (fifo_sync D4_W1590/W2048, ram_sdp D4_W3237/W4096,
  ram_sp D4_W3136), but needs 125-263s; with the old (0-12 asserts) sets it proved the frontier size in ~30s, so the
  larger assert set costs sby time at the old frontier and wins beyond it (at a 300s budget).
- pl_stage: sby spends ~3.5-4 of its 300s in model preparation (yosys + aig for ~17k asserts with clk2fflogic);
  seq_prove needs 365s total, i.e. also over a 300s budget. Neither is clearly better there.
- fifo_sync: seq_prove 1.1-1.4x faster. RAMs: sby (aiger-suprove) clearly better, seq_prove >300s (ram_sdp W3236: 566s).
