# xorgrid: one-by-one proof of internal equalities (yosys-smtbmc --incremental)

    ./build_case.sh <.../xorgrid/run/I16_O16_C16_W10_H10_...> case_w10   # -> case_w10/miter_sync.smt2
    python3 seq_prove.py case_w10/miter_sync.smt2 --k 2 --src case_w10/asserts.vh

`../seqprove/vendor/smtbmc_incremental.py` (was `pylib/`) is copied from the yosys checkout (not shipped in OSS CAD Suite);
`seq_prove.py` puts it on PYTHONPATH for the smtbmc subprocess.

Findings
- Model must be built WITHOUT `clk2fflogic` (see build_case.sh). With it, ~600 extra `#sampled` state bits
  are unconstrained by the equalities and no candidate is k-inductive for any k tried (1..3).
- Candidates are not provable one at a time with only proven lemmas (cyclic dependency between registers);
  seq_prove.py therefore assumes all live candidates as retractable hypotheses (update_assumptions),
  checks them one after another and retracts failures immediately (Houdini). Survivors are jointly k-inductive.
- k=1 is not enough on the sync model, k=2 is.
- Negative test: case_w4_neg has two bogus asserts appended; both are refuted, the 97 real ones stay proven.

Timing (z3, k=2): W4 97 asserts 0.6s, W10 601 asserts 25s, W16 1537 asserts 284s.

Assert order / batching (2026-09-25)
- `--order index|reverse|colmajor|random`: no measurable effect (within +-15% noise, random as good as any),
  with or without chunking. All candidates survive the first sweep, so order cannot save checks, and the
  solver keeps no useful state between checks that a clever order could exploit.
- `--goal assume` (negated goal as check-sat-assuming literal instead of push/pop, keeps learned clauses): no gain.
- `--chunk N`: one query per N candidates (OR of negations); only on sat fall back to one by one.
  This is where the gain is. N=16 is the sweet spot; one query for everything (N>=#asserts) is 4-10x SLOWER
  than N=1 (W10 z3 86s, yices 43s).
    W10 boolector 11.1s -> 1.8s, yices 3.4s -> 1.4s, z3 21.9s -> 14.3s
    W16 boolector 46s -> 5.6-7.6s, yices 30s -> 10s
    W24 boolector 205s -> 29s, yices 232s -> 58s
    W32 boolector TIMEOUT(600s) -> 67s, yices TIMEOUT -> 197s   (6145 asserts)
- `--model`: on sat, `get-value` all live candidates and drop every one the model violates (classic Houdini).
  No effect when all survive (xorgrid); 1.3-3x when many fail (corescore, see ../corescore_scaling/README.md).
- NOTE: asserts in the miter are clocked (`always @(posedge clk)`), each gets a sampling register, so `--k 2`
  here is 1-induction on the real registers (that is why "k=1 is not enough, k=2 is"). See ../corescore_scaling/README.md.
