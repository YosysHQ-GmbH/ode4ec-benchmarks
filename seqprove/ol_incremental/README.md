# ol_* benchmarks through seq_prove (2026-09-25)

    ./run_case.sh <benchmark> <run> <old|new> [timeout]     # appends to results.csv

`new` regenerates the asserts with the fixed generator (memory naming fix, match_gate_wires, const_candidates);
`old` uses the run's own asserts.vh. Model: the run's own sby script minus clk2fflogic (keeps fminit reset
sequence), asserts moved to `always @*`. seq_prove: yices, k=2, --chunk 16 --model, 300s timeout, 4 jobs in
parallel on 16 cores. ol_fifo_async skipped (two clocks). Cases in cases.txt: per benchmark the largest size
sby proved with internal asserts (IA), the next larger size sby did not prove, and the largest size overall.

sby IA timeouts were 30s (60s for arb_prio); "sby" below = best IA time from run/results.csv. Only abc-pdr, aiger-suprove,
aiger-rIC3 prove; btormc, btor-rIC3, smtbmc-* run `mode bmc` (depth 20), so their PASS is bounded, not a proof.

| benchmark    | run            | sby IA      | asserts old -> new | seq_prove new | seq_prove old |
|--------------|----------------|-------------|--------------------|---------------|---------------|
| arb_prio     | W16_L410       | PASS 60s    | 6560 = 6560        | PASS 50s      |               |
| arb_prio     | W16_L411       | fail (60s)  | 6576 = 6576        | PASS 49s      |               |
| arb_prio     | W16_L512       | fail (60s)  | 8192 = 8192        | PASS 80s      |               |
| arb_rr       | W512 (largest) | PASS 22s    | 511 -> 512         | PASS 151s     | PASS 154s     |
| arb_wrr      | G112           | PASS 24s    | 684 -> 685         | PASS 20s      |               |
| arb_wrr      | G128           | fail (30s)  | 780 -> 781         | PASS 29s      | PASS 29s      |
| dyn_sft      | W440_M220      | PASS 29s    | 1335 -> 1347       | PASS 41s      |               |
| dyn_sft      | W1152_M4       | fail (30s)  | 2309 -> 2312       | PASS 105s     | PASS 110s     |
| dyn_sft      | W2048_M4       | fail (30s)  | 4101 -> 4104       | TIMEOUT       |               |
| fifo_sync    | D4_W1589       | PASS 28s    | 12 -> 6368         | PASS 103s     |               |
| fifo_sync    | D4_W1590       | fail (30s)  | 12 -> 6372         | PASS 109s     | 18/19 (fails) |
| fifo_sync    | D4_W2048       | fail (30s)  | 12 -> 8204         | PASS 171s     |               |
| pl_stage     | W16_S479       | BMC-only 30s (no proof) | 0 -> 16765         | PASS 280s     |               |
| pl_stage     | W16_S480       | fail (30s)  | 0 -> 16800         | PASS 283s     | 0/3 (fails)   |
| pl_stage     | W16_S512       | fail (30s)  | 0 -> 17920         | TIMEOUT       |               |
| ram_sdp      | D4_W3236       | PASS 30s    | 0 -> 12944         | TIMEOUT (PASS 566s w/ 600s, chunk 64) | |
| ram_sdp      | D4_W3237       | fail (30s)  | 0 -> 12948         | TIMEOUT       | 0/1 (fails)   |
| ram_sdp      | D4_W4096       | fail (30s)  | 0 -> 16384         | TIMEOUT       |               |
| ram_sp       | D4_W3135/3136/4096 | PASS 30s / fail / fail | 0 -> 12540..16384 | TIMEOUT (all) | |
| tdm          | C1_W8, C4_W1   | fail        | 2, 9               | 4/5, 12/12 (<1s) |            |
| wconv_n2m    | I4_O4, I4_O2   | fail        | 0, 12              | PASS (<1s)    |               |
| wconv_n2xn   | I4_O4, I1_O2   | fail        | 0, 12 -> 13        | PASS (<1s)    | PASS          |
| wconv_xn2n   | I4_O4, I2_O1   | fail        | 0, 6               | PASS (<1s)    |               |

Notes
- The memory naming bug also hit fifo_sync, pl_stage, ram_sdp, ram_sp (register arrays go through memory_map):
  their existing IA runs had 0-12 internal asserts, i.e. sby's "IA" frontier there is effectively a plain miter.
- const_candidates made no difference here (old asserts prove the same cases equally fast).
- sby's failures are 30/60s timeouts, so a seq_prove PASS in more than 30s is not a like-for-like win.
  Cases proven within sby's own time limit where sby failed: arb_prio W16_L411 (49s < 60s), arb_wrr G128 (29s < 30s).
- tdm C1_W8: the Out_Data assert is constant false after yosys (In_ChSel is $clog2(1) = 0 bits wide, "Resizing
  cell port ... from 2 bits to 0 bits"); a miter bug at CHANNEL=1, also explains sby's MI FAIL there.
- tdm/wconv_*: sby shows HARDTIMEOUT with 0s for every engine on 7-66 cell designs, looks like a harness failure,
  not a hard problem; seq_prove proves them in <1s.
- RAM designs: per-check cost is the problem, larger chunks do not help (ram_sdp W3236: chunk 16 >300s,
  chunk 64 566s, chunk 256 587s).

Update: sby rerun with these asserts and 300s, plus seq_prove build times: see ../ol_sby/README.md.
