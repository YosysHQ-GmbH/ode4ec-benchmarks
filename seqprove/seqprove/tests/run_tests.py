#!/usr/bin/env python3
"""Regression tests for build_model.py + seq_prove.py on tiny designs with known answers.

usage: python3 tests/run_tests.py [--keep]      (work dirs in seqprove/runs/tests/)

Each case is a one-module "miter" run dir (miter.v + miter_extra_asserts.sby). Expected is either the
seq_prove result or `build: <text>` for a model the builder must refuse.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEQ = HERE.parent
WORK = SEQ.parent / "runs" / "tests"

SBY = """[options]
mode prove
[engines]
smtbmc
[script]
{read}
hierarchy -top miter
flatten
{extra}async2sync
clk2fflogic
[files]
miter.v
{filelist}"""

# the reset sequence of the frontier benchmarks: flip-flops without init value start at 0, reset is held
# for the first two clock edges and free afterwards
RESET_SEQ = {"extra": """proc
fminit -seq rst_n 0,0,'z -posedge clk
setundef -undriven -init -zero
"""}
NO_RESET_SEQ = {"extra": "proc\nsetundef -undriven -init -zero\n"}
# the frontend the cva6 miter is read with (read_verilog has no `assert ... else $error(...)`)
SLANG = {"read": "plugin -i slang\nread_slang --top miter miter.v"}

CASES = {
    # name: (k, expected, verilog[, dict(read=frontend lines, extra=script lines before async2sync)])
    "equal": (2, "PASS", """
module miter(input clk, input d); reg a = 0, b = 0;
  always @(posedge clk) begin a <= d; b <= d; end
  always @(posedge clk) begin
    assert(a == b);
  end
endmodule"""),
    "different": (2, "FAIL", """
module miter(input clk, input d); reg a = 0, b = 0;
  always @(posedge clk) begin a <= d; b <= !d; end
  always @(posedge clk) begin
    assert(a == b);
  end
endmodule"""),
    # r2 is 1 only at step 2 (= K): the step case (non-initial states) cannot see it, only a base case
    # that covers step K does. A base case to K-1 would report PASS here.
    "initstate_at_k": (2, "FAIL", """
module miter(input clk); reg r1 = 0, r2 = 0;
  always @(posedge clk) begin r1 <= $initstate; r2 <= r1; end
  always @* assert(r2 == 0);
endmodule"""),
    # contradictory design assumption: every check would be vacuously unsat
    "vacuous_assume": (2, "ERROR", """
module miter(input clk, input d); reg a = 0, b = 0;
  always @(posedge clk) begin a <= d; b <= !d; end
  always @* assume(d && !d);
  always @* assert(a == b);
endmodule"""),
    # --wide-bits routing: the 64-bit output equality goes to a boolector session
    "wide_equal": ((2, "--wide-bits", "32", "--wide-solver", "boolector"), "PASS", """
module miter(input clk, input [63:0] d); reg [63:0] a = 0, b = 0;
  always @(posedge clk) begin a <= d ^ {d[31:0], d[63:32]}; b <= {d[63:32] ^ d[31:0], d[31:0] ^ d[63:32]}; end
  always @(posedge clk) begin
    assert(a == b);
  end
endmodule"""),
    "wide_different": ((2, "--wide-bits", "32", "--wide-solver", "boolector"), "FAIL", """
module miter(input clk, input [63:0] d); reg [63:0] a = 0, b = 0;
  always @(posedge clk) begin a <= d ^ {d[31:0], d[63:32]}; b <= {d[63:32] ^ d[31:0], d[31:0] ^ d[63:33], 1'b0}; end
  always @(posedge clk) begin
    assert(a == b);
  end
endmodule"""),
    # refused by the build's clock guard
    "two_clocks": (2, "build: flip-flops not all clocked by one 1-bit top-level input", """
module miter(input clk, input clk2, input d); reg a = 0, b = 0;
  always @(posedge clk) a <= d; always @(posedge clk2) b <= d;
  always @(posedge clk) begin
    assert(a == b);
  end
endmodule"""),
    "negedge": (2, "build: negedge flip-flops", """
module miter(input clk, input d); reg a = 0, b = 0;
  always @(posedge clk) a <= d; always @(negedge clk) b <= d;
  always @(posedge clk) begin
    assert(a == b);
  end
endmodule"""),
    "latch": (2, "build: latches", """
module miter(input clk, input e, input d); reg a, b = 0;
  always @* if (e) a = d; always @(posedge clk) b <= d;
  always @(posedge clk) begin
    assert(a == b);
  end
endmodule"""),
    # b is clocked by gated logic: one step per clock cycle would update it with a (a false PASS)
    "gated_clock": (2, "build: flip-flops not all clocked by one 1-bit top-level input", """
module miter(input clk, input e, input d); reg a = 0, b = 0; wire g = clk & e;
  always @(posedge clk) a <= d; always @(posedge g) b <= d;
  always @(posedge clk) begin
    assert(a == b);
  end
endmodule"""),
    "logic_in_assert_block": (2, "build: more than asserts", """
module miter(input clk, input d); reg a = 0, b = 0, c = 0;
  always @(posedge clk) begin a <= d; b <= d; end
  always @(posedge clk) begin
    c <= a;
    assert(a == b);
  end
endmodule"""),
    "always_ff_else_error": (2, "PASS", """
module miter(input clk, input d); reg a = 0, b = 0;
  always @(posedge clk) begin a <= d; b <= d; end
  always_ff @(posedge clk) begin
    assert(a == b) else $error("a/b mismatch");
  end
endmodule""", SLANG),
    "always_ff_else_error_diff": (2, "FAIL", """
module miter(input clk, input d); reg a = 0, b = 0;
  always @(posedge clk) begin a <= d; b <= !d; end
  always_ff @(posedge clk) begin
    assert(a == b) else $error("a/b mismatch");
  end
endmodule""", SLANG),
    # gold: register with async reset value 1 and next state 1; gate: the constant 1 (what synthesis makes
    # of it). Equal only after a reset: without one the register starts at its init value 0.
    "reset_const_no_reset": (2, "FAIL", """
module miter(input clk, input rst_n); reg a;
  always @(posedge clk or negedge rst_n) if (!rst_n) a <= 1; else a <= 1;
  always @(posedge clk) begin
    assert(a == 1'b1);
  end
endmodule""", NO_RESET_SEQ),
    "reset_const_reset_seq": (2, "PASS", """
module miter(input clk, input rst_n); reg a;
  always @(posedge clk or negedge rst_n) if (!rst_n) a <= 1; else a <= 1;
  always @(posedge clk) begin
    assert(a == 1'b1);
  end
endmodule""", RESET_SEQ),
    # 'z after the sequence leaves the reset free, so it may come back later: r2 records a reset while r3
    # (r1 a cycle ago, r1 = "out of reset for a cycle") is set, first possible at step 4, visible at step 5
    "reset_seq_rereset": (6, "FAIL", """
module miter(input clk, input rst_n); reg r1; reg r2, r3;
  always @(posedge clk or negedge rst_n) if (!rst_n) r1 <= 0; else r1 <= 1;
  always @(posedge clk) begin r3 <= r1; r2 <= r2 | (r3 & !rst_n); end
  always @(posedge clk) begin
    assert(!r2);
  end
endmodule""", RESET_SEQ),
}

# --output-bit-candidates: one candidate per bit of each equality property (miter_bits.vh)
BITS = {"build": ["--output-bit-candidates"]}
BITS_PROVE = ("--candidates", "miter_bits.vh")
# P1 = {x, y} vs {x2, z} is not 1-inductive (unreachable state 3); P2 = x[3:1] vs x2[3:1] needs x[0] == x2[0].
# Without bit candidates P2 falls with P1; with them P1's x bits stay and prove P2 (P1 stays unproven).
PARTIAL = """
module miter(input clk, input [3:0] d);
  reg [3:0] x = 0, x2 = 0; reg [1:0] y = 0, z = 0;
  always @(posedge clk) begin
    x <= x + d; x2 <= x2 + d;
    y <= (y == 2) ? 2'd0 : y + 2'd1;
    z <= (z == 2) ? 2'd0 : (z == 3) ? 2'd3 : z + 2'd1;
  end
  wire [5:0] oa = {x, y}, ob = {x2, z};
  wire [2:0] pa = x[3:1], pb = x2[3:1];
  always @(posedge clk) begin
    assert(oa == ob);
    assert(pa == pb);
  end
endmodule"""
# equal 16-bit products, one from `*`, one from a shift-add loop: the query is out of reach of bit-level SAT
# (no answer within a minute). --query-timeout retracts the property: UNKNOWN, never PASS or FAIL.
MUL16 = """
module miter(input clk, input [15:0] a, input [15:0] b);
  reg [31:0] p = 0, q = 0;
  function [31:0] mul(input [15:0] x, input [15:0] y);
    integer i;
    begin
      mul = 0;
      for (i = 0; i < 16; i = i + 1)
        if (y[i]) mul = mul + ({16'b0, x} << i);
    end
  endfunction
  always @(posedge clk) begin p <= a * b; q <= mul(a, b); end
  always @(posedge clk) begin
    assert(p == q);
  end
endmodule"""
# candidates on middle bits of MUL16's products, each out of reach: --timeout-siblings retracts the others
# after the first timeout (2 rebuilds instead of 1 + 4)
MUL16_CANDS = MUL16.replace("    assert(p == q);", "    assert(r == s);\n    `include \"cands.vh\"").replace(
    "reg [31:0] p = 0, q = 0;", "reg [31:0] p = 0, q = 0; reg r = 0, s = 0;").replace(
    "q <= mul(a, b); end", "q <= mul(a, b); r <= a[0]; s <= a[0]; end")
CANDS_VH = "".join(f"    assert(p[{i}] == q[{i}]);\n" for i in (12, 13, 14, 15))
SIB = {"files": {"cands.vh": CANDS_VH}}
SIB_PROVE = ("--candidates", "cands.vh", "--src", "{dir}/cands.vh", "--chunk", "4", "--query-timeout", "2")
CASES.update({
    "timeout_siblings": ((2, *SIB_PROVE, "--timeout-siblings"),
                         "PASS @ 4 timed out); layers L0 5 L1 0; 2 session restarts", MUL16_CANDS, SIB),
    "timeout_no_siblings": ((2, *SIB_PROVE), "PASS @ 4 timed out); layers L0 5 L1 0; 5 session restarts",
                            MUL16_CANDS, SIB),
    # four guards over the same hard equality: one group (2 restarts instead of 5)
    "timeout_siblings_guarded": ((2, *SIB_PROVE, "--timeout-siblings"),
                                 "PASS @ 4 timed out); layers L0 5 L1 0; 2 session restarts", MUL16_CANDS,
                                 {"files": {"cands.vh": "".join(
                                     f"    assert({g} || (p[15:12] == q[15:12]));\n" for g in ("!r", "r", "!s", "s"))}}),
    # two chunks of two bits: the group is retracted after the first single timeout (2 restarts) ...
    "timeout_siblings_2chunks": ((2, *SIB_PROVE, "--chunk", "2", "--timeout-siblings"),
                                 "PASS @ 4 timed out); layers L0 5 L1 0; 2 session restarts", MUL16_CANDS, SIB),
    # ... but a name wider than --sibling-max only loses its bits of the chunk at hand (4 restarts)
    "timeout_siblings_wide_name": ((2, *SIB_PROVE, "--chunk", "2", "--timeout-siblings", "--sibling-max", "2"),
                                   "PASS @ 4 timed out); layers L0 5 L1 0; 4 session restarts", MUL16_CANDS, SIB),
    "query_timeout": ((2, "--query-timeout", "2"), "UNKNOWN @ properties 0/1 proven (1 timed out)", MUL16),
    # bitwuzla stops the check itself (--time-limit-per, answer unknown): no session rebuild
    "query_timeout_solver": ((2, "--query-timeout", "2", "--solver", "bitwuzla"),
                             "UNKNOWN @ properties 0/1 proven (1 timed out)", MUL16),
    "query_timeout_easy": ((2, "--query-timeout", "5"), "PASS @ properties 1/1 proven (0 timed out)",
                           CASES["equal"][2]),
    "bits_equal": ((2, *BITS_PROVE), "PASS", CASES["wide_equal"][2], BITS),
    # a 1 MiB limit rebuilds the base and the step session after every chunk: same answers
    "session_mem_rebuild": ((2, "--session-mem-gb", "0.001"), "PASS @ 2 memory rebuilds", CASES["equal"][2]),
    "session_mem_bits_different": ((2, *BITS_PROVE, "--session-mem-gb", "0.001", "--chunk", "16", "--model"),
                                   "FAIL", CASES["wide_different"][2], BITS),
    "bits_different": ((2, *BITS_PROVE), "FAIL", CASES["wide_different"][2], BITS),
    "bits_partial_without": (1, "UNKNOWN @ properties 0/2 proven", PARTIAL),
    "bits_partial_with": ((1, *BITS_PROVE), "UNKNOWN @ properties 1/2 proven", PARTIAL, BITS),
})



# regenerated candidates (build_model.py --regen) on a gold RTL / synthesized gate pair
LIB = SEQ.parents[1] / "internal_assertions" / "sky130" / "sky130_fd_sc_hd__tt_025C_1v80.lib"

# 5-state FSM, async reset; `synth` re-encodes state_q one-hot (3 gold bits -> 5 gate bits; the attribute
# forces fsm_detect on this small FSM)
FSM_RTL = """
module dut(input clk, input rst, input [1:0] in, output out);
  localparam IDLE = 3'd0, A = 3'd1, B = 3'd2, C = 3'd3, D = 3'd4;
  (* fsm_encoding = "one-hot" *) reg [2:0] state_q;
  reg [2:0] state_d;
  always @* begin
    state_d = state_q;
    case (state_q)
      IDLE: if (in[0]) state_d = A;
      A: state_d = in[1] ? B : C;
      B: state_d = D;
      C: state_d = (in == 2'b11) ? IDLE : D;
      D: state_d = IDLE;
      default: state_d = IDLE;
    endcase
  end
  always @(posedge clk or posedge rst) if (rst) state_q <= IDLE; else state_q <= state_d;
  assign out = (state_q == `OUT_STATE) || (state_q == D && in[0]);
endmodule
"""

GOLD_YS = """read_verilog -DOUT_STATE=B rtl.v
hierarchy -top dut
proc
flatten
hierarchy -top dut
memory_map -formal
opt_clean
rename dut gold_top
write_rtlil gold.il
"""

# as internal_assertions/*/synth.tcl: synth, sky130 flip-flops and gates, bit-split nets
GATE_YS = """read_verilog -DOUT_STATE={out_state} rtl.v
synth -top dut -run :check
dfflibmap -liberty {lib}
abc -liberty {lib}
splitnets
setundef -zero
opt
opt_clean -purge
{extra}rename dut gate_top
write_rtlil gate.il
"""

REGEN_MITER = """module miter(input clk, input rst, input [1:0] in);
  wire out_a, out_b;
`ifdef INTERNAL_ASSERTS
  `include "decls.vh"
`endif
  gold_top dut_a(.clk(clk), .rst(rst), .in(in), .out(out_a)
`ifdef INTERNAL_ASSERTS
  `include "ports_a.vh"
`endif
  );
  gate_top dut_b(.clk(clk), .rst(rst), .in(in), .out(out_b)
`ifdef INTERNAL_ASSERTS
  `include "ports_b.vh"
`endif
  );
  always @(posedge clk) begin
    assert(out_a == out_b);
`ifdef INTERNAL_ASSERTS
    `include "asserts.vh"
`endif
  end
endmodule
"""

REGEN_SBY = """[options]
mode prove
[engines]
smtbmc
[script]
read_rtlil gold.il
read_liberty -ignore_miss_func {libname}
read_rtlil gate.il
script expose.ys
plugin -i slang
read_slang --top miter miter.v -D INTERNAL_ASSERTS
hierarchy -top miter
flatten
fminit -seq rst 1,'z -posedge clk
setundef -zero
setundef -undriven -init -zero
async2sync
clk2fflogic
[files]
{lib}
miter.v
gold.il
gate.il
"""

# registers whose RTLIL bit positions differ from their HDL indices (gold `\v [0]`, gate `v[1]`), and one
# that is constant after reset (removed in the gate); the output needs all of them in the step case
PIPE_RTL = """
module dut(input clk, input rst, input [1:0] in, output out);
  localparam B = 2'd1, C = 2'd2;
  reg [0:1] v;   // as in fpnew pipelines: v[0] is the combinational input stage, v[1] a register
  reg [4:3] c;   // offset 3
  reg [5:7] u;   // ascending, offset 5
  reg k;         // holds its reset value 1 (as an LFSR that never shifts)
  always @* v[0] = in[0];
  always @(posedge clk or posedge rst)
    if (rst) begin v[1] <= 1'b0; c <= 2'd0; u <= 3'd0; k <= 1'b1; end
    else begin
      v[1] <= v[0];
      if (v[1]) c <= c + 2'd1;
      u <= {u[6:7], c[4] ^ in[1]};
      k <= k;
    end
  assign out = k & ((c == `OUT_STATE) ^ u[5]);
endmodule
"""

# f counts 0, 1, 2, 0, ...; only at the unreachable f == 3 does t depend on sel[0] (a don't-care resolved
# differently), invisible at the output for any k: the proof needs f != 3. sel[1] differs at reachable f == 2.
RANGE_RTL = """
module dut(input clk, input rst, input [1:0] in, output out);
  localparam [1:0] B = 2'b00, C = 2'b01, D = 2'b10;
  wire [1:0] sel = `OUT_STATE;
  reg [1:0] f;
  reg t;
  always @(posedge clk or posedge rst)
    if (rst) begin f <= 2'd0; t <= 1'b0; end
    else begin
      if (in[0]) f <= (f == 2'd2) ? 2'd0 : f + 2'd1;
      t <= t ^ in[1] ^ ((f == 2'd3) & sel[0] & in[1]);
    end
  assign out = t ^ (f == 2'd1) ^ ((f == 2'd2) & sel[1]);
endmodule
"""

# d and p[1:0] hold a don't-care (resolved differently, sel[0]) while their valid bit (v, p[2]) is clear,
# and t only reads them when valid: the proof needs `v -> d equal` and `p[2] -> p equal` (the plain
# equalities are false in reachable states). sel[1] changes t whenever v is set (a real difference).
GUARD_RTL = """
module dut(input clk, input rst, input [1:0] in, output out);
  localparam [1:0] B = 2'b00, C = 2'b01, D = 2'b10;
  wire [1:0] sel = `OUT_STATE;
  wire ld = in[1];
  wire use = in[0] & ~in[1];
  reg v, t;
  reg [1:0] d;
  reg [2:0] p;
  always @(posedge clk or posedge rst)
    if (rst) begin v <= 1'b0; d <= 2'd0; p <= 3'd0; t <= 1'b0; end
    else begin
      if (ld) begin
        v <= in[0];
        d <= in[0] ? {t, ~t} : {2{sel[0]}};
        p <= {~in[0], ~in[0] ? {t, ~t} : {2{sel[0]}}};
      end
      t <= t ^ in[0] ^ (use & v & d[1] & d[0]) ^ (use & p[2] & p[1] & p[0]) ^ (v & sel[1]);
    end
  assign out = t ^ v;
endmodule
"""

# as FSM_RTL with a 4-bit state register and 3 used states: the one-hot gate register has fewer bits than
# gold, same names, unrelated bits (as cva6's axi_shim)
RECODE_RTL = """
module dut(input clk, input rst, input [1:0] in, output out);
  localparam [3:0] IDLE = 4'd0, A = 4'd1, B = 4'd2;
  (* fsm_encoding = "one-hot" *) reg [3:0] state_q;
  reg [3:0] state_d;
  always @* begin
    state_d = state_q;
    case (state_q)
      IDLE: if (in[0]) state_d = A;
      A: state_d = in[1] ? B : IDLE;
      B: state_d = in[1] ? B : IDLE;
      default: state_d = IDLE;
    endcase
  end
  always @(posedge clk or posedge rst) if (rst) state_q <= IDLE; else state_q <= state_d;
  assign out = (state_q == `OUT_STATE) || (state_q == A && in[0]);
endmodule
"""

# a submodule register drives its output port q; splitnets before flatten leaves ports whole, so the gate
# keeps `s.q` as one 4-bit wire while the candidates name `s.q[i]` (as neorv32's shifter rs1_i)
SUBVEC_RTL = """
module sub(input clk, input rst, input d, output reg [3:0] q);
  always @(posedge clk or posedge rst) if (rst) q <= 4'd0; else q <= {q[2:0], d};
endmodule
module dut(input clk, input rst, input [1:0] in, output out);
  localparam [3:0] B = 4'd3, C = 4'd1;
  wire [3:0] w;
  sub s(.clk(clk), .rst(rst), .d(in[0]), .q(w));
  assign out = (w == `OUT_STATE) ^ in[1];
endmodule
"""
SUBVEC_GATE = "flatten\nhierarchy -top dut\n"

DEFER = ["--defer-implied", "--src", "{out}/asserts.vh"]

REGEN_CASES = {
    # name: (gate OUT_STATE, build_model args, seq_prove args, expected[, {"rtl": ..., "gate": script lines}])
    "fsm_onehot_equal": ("B", ["--fsm-candidates"], ["--k", "2"], "PASS"),
    # the same pair with only name-matched candidates: gold bit j vs gate one-hot bit j is meaningless
    "fsm_onehot_no_fsm_candidates": ("B", [], ["--k", "2"], "UNKNOWN"),
    # gate decodes state C instead of B: reachable at step 3 after the reset (base case 0..3 with k=4)
    "fsm_onehot_different": ("C", ["--fsm-candidates"], ["--k", "4"], "FAIL"),
    # as after abc: state flip-flops named after other nets (internal $ name, other name in the scope)
    "fsm_onehot_renamed_bits": ("B", ["--fsm-candidates"], ["--k", "2"], "PASS",
                                {"gate": "cd dut\nrename state_q[3] $abc$1$renamed\nrename state_q[1] other_q\ncd ..\n"}),
    "fsm_fewer_bits_equal": ("B", ["--fsm-candidates"], ["--k", "2"], "PASS", {"rtl": RECODE_RTL}),
    "fsm_fewer_bits_no_fsm_candidates": ("B", [], ["--k", "2"], "UNKNOWN", {"rtl": RECODE_RTL}),
    # gate decodes state A instead of B: reached at step 2 after the reset (base case 0..3 with k=4)
    "fsm_fewer_bits_different": ("A", ["--fsm-candidates"], ["--k", "4"], "FAIL", {"rtl": RECODE_RTL}),
    "pipe_upto_offset_const_equal": ("B", ["--const-candidates"], ["--k", "2"], "PASS", {"rtl": PIPE_RTL}),
    # without the constant candidates k is free in the step case
    "pipe_upto_offset_no_const": ("B", [], ["--k", "2"], "UNKNOWN", {"rtl": PIPE_RTL}),
    # gate compares c with C instead of B: c == B at step 3 (base case 0..3 with k=4)
    "pipe_upto_offset_different": ("C", ["--const-candidates"], ["--k", "4"], "FAIL", {"rtl": PIPE_RTL}),
    # gold and gate differ only in the unreachable state f == 3: needs the invariant f != 3
    "range_unreachable_equal": ("C", ["--range-candidates"], ["--k", "2"], "PASS", {"rtl": RANGE_RTL}),
    "range_unreachable_no_range": ("C", [], ["--k", "2"], "UNKNOWN", {"rtl": RANGE_RTL}),
    # they differ at f == 2, reached at step 3 (base case 0..3 with k=4): no range candidate may hide it
    "range_reachable_different": ("D", ["--range-candidates"], ["--k", "4"], "FAIL", {"rtl": RANGE_RTL}),
    "guarded_equal": ("C", ["--guarded-candidates"], ["--k", "2"],
                      "PASS @ candidates 10/25 proven (0 falsified in base, 15 retracted, 0 timed out)",
                      {"rtl": GUARD_RTL}),
    "guarded_no_guards": ("C", [], ["--k", "2"], "UNKNOWN", {"rtl": GUARD_RTL}),
    # v is set at step 2, t differs at step 3 (base case 0..3 with k=4)
    "guarded_different": ("D", ["--guarded-candidates"], ["--k", "4"], "FAIL", {"rtl": GUARD_RTL}),
    # --defer-implied: the proof needs the guarded equalities of d and p, so they must be woken
    # a woken assert false from the initial state must not be assumed before its base check (same sweeps)
    "defer_woken_false_in_base": ("B", ["--fsm-candidates", "--guarded-candidates"],
                                  ["--k", "2", "--chunk", "16", "--model", *DEFER],
                                  ("PASS @ candidates 104/123 proven (9 falsified in base, 10 retracted, 0 timed out, "
                                  "0 of 8 deferred never needed) @ sweeps 2,"), {"rtl": RECODE_RTL}),
    "defer_woken_reference": ("B", ["--fsm-candidates", "--guarded-candidates"],
                              ["--k", "2", "--chunk", "16", "--model"],
                              ("PASS @ candidates 104/123 proven (9 falsified in base, 10 retracted, 0 timed out) "
                              "@ sweeps 2,"), {"rtl": RECODE_RTL}),
    "defer_guarded_equal": ("C", ["--guarded-candidates"], ["--k", "2", *DEFER],
                            ("PASS @ candidates 10/25 proven (0 falsified in base, 15 retracted, 0 timed out, "
                            "0 of 18 deferred never needed)"), {"rtl": GUARD_RTL}),
    "defer_guarded_different": ("D", ["--guarded-candidates"], ["--k", "4", *DEFER], "FAIL", {"rtl": GUARD_RTL}),
    # every bit equality holds: no guarded one is ever checked
    "defer_none_needed": ("B", ["--const-candidates", "--guarded-candidates"], ["--k", "2", *DEFER],
                          "PASS @ 14 of 14 deferred never needed", {"rtl": PIPE_RTL}),
    # --drop-from: the counterexample drops of an earlier run are taken over, same fixpoint (104/123)
    "drop_from_same_fixpoint": ("B", ["--fsm-candidates", "--guarded-candidates"],
                                ["--k", "2", "--chunk", "16", "--model", *DEFER, "--drop-from", "{out}/run1"],
                                ("PASS @ candidates 104/123 proven (0 falsified in base, 0 retracted, 0 timed out, "
                                "0 of 8 deferred never needed, 19 dropped in an earlier run)"),
                                {"rtl": RECODE_RTL, "first": ["--k", "2"]}),
    # ... but nothing after that run's first query timeout
    "drop_from_after_timeout": ("B", ["--fsm-candidates", "--guarded-candidates"],
                                ["--k", "2", "--chunk", "16", "--model", "--drop-from", "{out}/run1"],
                                "PASS @ candidates 104/123 proven (9 falsified in base, 10 retracted, 0 timed out)",
                                {"rtl": RECODE_RTL, "first": ["--k", "2"], "timeout_first": True}),
    # --resume-from: every retraction is taken over, also after a (faked) query timeout; same fixpoint
    "resume_same_fixpoint": ("B", ["--fsm-candidates", "--guarded-candidates"],
                             ["--k", "2", "--chunk", "16", "--model", *DEFER, "--resume-from", "{out}/run1"],
                             ("PASS @ candidates 104/123 proven (0 falsified in base, 0 retracted, 0 timed out, "
                              "0 of 8 deferred never needed, 19 dropped in an earlier run)"),
                             {"rtl": RECODE_RTL, "first": ["--k", "2"], "timeout_first": True}),
    # a property that is false is found again: properties are never taken over
    "resume_different": ("A", ["--fsm-candidates"], ["--k", "4", "--resume-from", "{out}/run1"],
                         "FAIL", {"rtl": RECODE_RTL, "first": ["--k", "4"]}),
    "resume_other_k": ("B", ["--fsm-candidates"], ["--k", "2", "--resume-from", "{out}/run1"],
                       "ERROR: --resume-from", {"rtl": RECODE_RTL, "first": ["--k", "3"]}),
    # --drop-from takes nothing from a run with another k
    "drop_from_other_k": ("B", ["--fsm-candidates"], ["--k", "2", "--drop-from", "{out}/run1"],
                          "ERROR: --drop-from", {"rtl": RECODE_RTL, "first": ["--k", "3"]}),
    # a real difference is still found (the property is never taken over)
    "drop_from_different": ("A", ["--fsm-candidates"], ["--k", "4", "--drop-from", "{out}/run1"],
                            "FAIL", {"rtl": RECODE_RTL, "first": ["--k", "4"]}),
    # --order values-first: value constraints before register pairs, same results
    "values_first_fsm": ("B", ["--fsm-candidates"], ["--k", "2", "--order", "values-first"], "PASS"),
    "values_first_range": ("C", ["--range-candidates"], ["--k", "2", "--order", "values-first"], "PASS",
                           {"rtl": RANGE_RTL}),
    "values_first_different": ("D", ["--range-candidates"], ["--k", "4", "--order", "values-first"], "FAIL",
                               {"rtl": RANGE_RTL}),
    # gate bits on a multi-bit wire that is not split (see SUBVEC_RTL)
    "unsplit_gate_vector_equal": ("B", [], ["--k", "2"], "PASS", {"rtl": SUBVEC_RTL, "gate": SUBVEC_GATE}),
    # gate compares w with C = 1 instead of B = 3: w == 1 one shift after the reset (base case 0..3, k=4)
    "unsplit_gate_vector_different": ("C", [], ["--k", "4"], "FAIL", {"rtl": SUBVEC_RTL, "gate": SUBVEC_GATE}),
}


def run_regen_case(name, out_state, build_args, prove_args, opts=None):
    opts = opts or {}
    gate_extra = opts.get("gate", "")
    d = WORK / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    (d / "rtl.v").write_text(opts.get("rtl", FSM_RTL))
    (d / "gold.ys").write_text(GOLD_YS)
    (d / "gate.ys").write_text(GATE_YS.format(out_state=out_state, lib=LIB, extra=gate_extra))
    for ys in ("gold.ys", "gate.ys"):
        y = subprocess.run(["yosys", "-q", ys], cwd=d, capture_output=True, text=True, check=False)
        if y.returncode:
            return f"setup: yosys {ys} failed: {(y.stderr or y.stdout).strip()[-300:]}"
    (d / "miter.v").write_text(REGEN_MITER)
    (d / "miter_extra_asserts.sby").write_text(REGEN_SBY.format(lib=LIB, libname=LIB.name))
    b = subprocess.run([sys.executable, str(SEQ / "build_model.py"), str(d), str(d / "out"), "--regen",
                        *build_args], capture_output=True, text=True, check=False)
    if b.returncode:
        return "build: " + (b.stderr or b.stdout).strip().split("\n")[-1]
    if "first" in opts:     # an earlier run of the same model, for --drop-from {out}/run1
        subprocess.run([sys.executable, str(SEQ / "seq_prove.py"), str(d / "out" / "model.smt2"),
                        "--candidates", "asserts.vh", "--out", str(d / "out" / "run1"), *opts["first"]],
                       capture_output=True, text=True, check=False)
        if opts.get("timeout_first"):   # as if that run had a query timeout before its first drop
            log = d / "out" / "run1" / "checks.jsonl"
            log.write_text('{"event": "restart", "t": 0, "session": "step", "secs": 0}\n' + log.read_text())
    p = subprocess.run([sys.executable, str(SEQ / "seq_prove.py"), str(d / "out" / "model.smt2"),
                        "--candidates", "asserts.vh", *[a.format(out=d / "out") for a in prove_args]],
                       capture_output=True, text=True, check=False)
    res = [ln for ln in p.stdout.split("\n") if ln.startswith("RESULT ")]
    if not res:
        return f"no RESULT (rc={p.returncode}): {p.stderr.strip()[-300:]}"
    props = [ln for ln in p.stdout.split("\n") if ln.startswith(("properties ", "sweeps "))]
    return res[-1][len("RESULT "):] + "".join(f" @ {ln}" for ln in props[-2:])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="keep the work dirs")
    ap.add_argument("--only", help="run only the cases whose name contains this")
    args = ap.parse_args()
    fails = 0
    for table in (CASES, REGEN_CASES) if args.only else ():
        for name in [n for n in table if args.only not in n]:
            del table[name]
    for name, (k, expected, verilog, *opts) in CASES.items():
        opts = {"read": "read_verilog -formal miter.v", "extra": "", **(opts[0] if opts else {})}
        d = WORK / name
        shutil.rmtree(d, ignore_errors=True)
        d.mkdir(parents=True)
        (d / "miter.v").write_text(verilog.strip() + "\n")
        for fname, content in opts.get("files", {}).items():
            (d / fname).write_text(content)
        (d / "miter_extra_asserts.sby").write_text(SBY.format(filelist="".join(f + "\n" for f in opts.get("files", {})),
                                                              **opts))
        b = subprocess.run([sys.executable, str(SEQ / "build_model.py"), str(d), str(d / "out"),
                            *opts.get("build", [])], capture_output=True, text=True, check=False)
        if b.returncode:
            got = "build: " + (b.stderr or b.stdout).strip().split("\n")[-1]
        else:
            k, *extra = k if isinstance(k, tuple) else (k,)
            extra = [a.format(dir=d) for a in extra]
            p = subprocess.run([sys.executable, str(SEQ / "seq_prove.py"), str(d / "out" / "model.smt2"),
                                "--k", str(k), *extra], capture_output=True, text=True, check=False)
            res = [ln for ln in p.stdout.split("\n") if ln.startswith("RESULT ")]
            got = res[-1][len("RESULT "):] if res else f"no RESULT (rc={p.returncode}): {p.stderr.strip()[-300:]}"
            props = [ln for ln in p.stdout.split("\n") if ln.startswith("properties ")]
            got += f" @ {props[-1]}" if props else ""
        # "RESULT @ properties n/m proven": the result prefix, and the proven count if given
        exp_res, _, exp_props = expected.partition(" @ ")
        ok = (got.startswith(exp_res) and exp_props in got) or \
            (expected.startswith("build: ") and expected[7:] in got)
        fails += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name:24s} expected {expected!r:30s} got {got[:110]!r}")
        if ok and not args.keep:
            shutil.rmtree(d)
    for name, (out_state, build_args, prove_args, expected, *opts) in REGEN_CASES.items():
        got = run_regen_case(name, out_state, build_args, prove_args, *opts)
        exp_res, *exp_more = expected.split(" @ ")     # result prefix, then substrings of the summary
        ok = got.startswith(exp_res) and all(e in got for e in exp_more)
        fails += not ok
        print(f"{'ok  ' if ok else 'FAIL'} {name:24s} expected {expected!r:30s} got {got[:110]!r}")
        if ok and not args.keep:
            shutil.rmtree(WORK / name)
    total = len(CASES) + len(REGEN_CASES)
    print(f"{total - fails}/{total} passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
