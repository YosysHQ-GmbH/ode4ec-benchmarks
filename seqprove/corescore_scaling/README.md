# corescore scaling: sby engines vs incremental one-by-one proof (../xorgrid_incremental/seq_prove.py)

Incremental proof on c2 (530 asserts, k=2), run 2026-09-25, nothing else running:

    yices     --chunk 1            44.0s  623 checks   (older inc.csv 138s was measured while sby jobs ran)
    yices     --chunk 16           47.1s  666 checks
    yices     --chunk 1 --model    32.6s  374 checks
    yices     --chunk 16 --model   37.7s  394 checks
    boolector --chunk 1           149.4s  623 checks
    boolector --chunk 1 --model    47.3s  230 checks
    boolector --chunk 16 --model   66.8s  254 checks

Every variant ends at PROVEN 0/530 (Houdini fixpoint, independent of order/batching).
Cause: the candidates miss the memories. The miter has ~16.4k state bits, the asserts cover 530; the RAMs
(serving.ram.mem, rf_ram.memory, emitter.ram.mem; ~7k flattened bits in gate) have no equality candidates,
so in the step case gold/gate memory contents differ freely, and the first check (all 530 assumed) already fails.
Unlike xorgrid (all candidates survive), --chunk does not help here; --model (drop every candidate the sat
model violates) does, 1.3-3x.

## Memory asserts (c2/ia_mem, c2/ia_wire), 2026-09-25
_common/generate_internal_asserts.py silently skipped all memories: memory_map names gold word registers
"mem[78]" (an 8-bit wire), gate bits "mem[78][2]"; match_wire_widhts treated "mem[78]" as a bit select.
Fixed (a bracketed name that is itself a wire is expanded). xorgrid W10 output is byte-identical after the fix.
c2: 529 -> 7697 asserts (+7168 memory bits).

Asserts sit in `always @(posedge i_clk)`: yosys adds one sampling register per assert (async2sync), so
seq_prove's `--k K` on miter_sync.smt2 is (K-1)-induction on the real registers. miter_comb.v / build_comb.ys
put the same asserts in `always @*`, so K is real.

    ia_mem  sync  model, 7698 asserts, yices --model            0/7698   515s
    ia_mem  sync  model, 7698 asserts, yices --chunk 16 --model 0/7698   832s
    ia_mem  comb  model, 7698 asserts, yices --model, real k=2  32/7698  406s
    ia_wire comb  model, 7960 asserts, yices --model, real k=2  32/7960 1028s

ia_wire: generate_assert_files(..., match_gate_wires=True) (opt-in, default off) pairs gold registers without a
gate flop of the same name with the gate *wire* of that name (buffered copies, e.g. arbiter.i_wb_cpu_dbus_dat =
buf(cpu.mem_if.dat), or logic where synthesis merged a flop): +262 asserts, now ~all gold state bits covered.
No base-case failure anywhere (no candidate is false), but with (nearly) all state equated the first step
check (all candidates assumed) still fails, starting at axis_mux arb_inst grant/mask regs. Equality alone is not
2-inductive here; unreachable-state behaviour differs between gold and gate, or higher k is needed. Not resolved.

## Arbiter failure analysed, c2 PROVEN (c2/ia_const), 2026-09-25
Step-case counterexample (scratchpad diag_step.py: all candidates assumed at steps 0,1, arb_inst candidates
negated at step 2): gold axis_mux.arb_inst.mask_reg = 2'b11 at steps 0/1. arbiter.v (LSB_PRIORITY "HIGH") only
ever sets mask to 11<<(idx+1) = 10/00, so mask_reg[0] is constant 0; synthesis removed it from gate, and the
generator had no candidate for it -> unconstrained in the step, gold grants port 0 via the masked path, gate
grants port 1 -> grant/mask equalities break and Houdini unravels ~everything from there.
Fix: generate_assert_files(..., const_candidates=True) (opt-in): gold register bits with no gate counterpart get
`assert(gold_bit == 1'b0)` (init value after setundef -init -zero). 22 such bits in c2 (mask_reg[0], the unused
rf second write port wdata1_r/wen1_r); yosys itself folds 20 of them, 2 remain.

    ia_const comb model, 7962 asserts, yices --model, real k=2            PROVEN 7962/7962  593s  (7962 checks)
    ia_const comb model, 7962 asserts, yices --chunk 16 --model, real k=2 PROVEN 7962/7962  126s  (498 checks)
    (for comparison, sby on c2: IA btor-btormc PASS 365s, MI btor-btormc 204s, MI btor-rIC3 156s)

The miter output asserts are included (q and uart_txd are the same gpio flop in both netlists, yosys merges the
two asserts into one). Generator needs match_gate_wires=True AND const_candidates=True, asserts in always @*.
