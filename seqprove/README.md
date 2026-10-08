# seqprove/

seq_prove, a new proof strategy for the eqy benchmarks. The code lives in `seqprove/`; the other
directories are records of earlier runs (their scripts and results are kept as they were).
Run outputs of the tool go to `runs/` (git-ignored).

| dir | what |
|---|---|
| `seqprove/` | **tool**: incremental Houdini k-induction over miter asserts (yosys-smtbmc --incremental), model builder, benchmark runner, mutant generator. See its README |
| `runs/` | outputs: `runs/models/` cached models, `runs/<tag>/results.csv`, `runs/mutants/` |
| `xorgrid_incremental/` | record: first incremental prover; its `seq_prove.py` is kept unchanged as the A/B baseline for `seqprove/` |
| `ol_incremental/`, `ol_sby/` | record: ol_* benchmarks through the old seq_prove and through sby at 300s |
| `corescore_scaling/`, `corescore_c8/` | record: corescore through the old seq_prove and sby (generator fixes: memories, gate wires, const candidates) |
| `serv_incremental/` | record: serv sby runs (MI vs IA, mutation) |
| `incremental_asserts/` | toy: per-assert BMC with the smtbmc incremental interface |

Machine: shared 30 GB desktop. At most one sby case (<= 7 engines) or a few seq_prove jobs at a time.
