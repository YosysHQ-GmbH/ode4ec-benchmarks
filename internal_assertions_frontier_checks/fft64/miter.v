`default_nettype none

module miter
  #(parameter WIDTH = 16)
   (
    input wire             clock,
    input wire             reset,
    input wire             di_en,
    input wire [WIDTH-1:0] di_re,
    input wire [WIDTH-1:0] di_im
   );

   wire             gold_do_en, gate_do_en;
   wire [WIDTH-1:0] gold_do_re, gate_do_re;
   wire [WIDTH-1:0] gold_do_im, gate_do_im;

`ifdef INTERNAL_ASSERTS
   `include "decls.vh"
`endif

   gold_top i_gold (
      .clock  (clock),
      .reset  (reset),
      .di_en  (di_en),
      .di_re  (di_re),
      .di_im  (di_im),
      .do_en  (gold_do_en),
      .do_re  (gold_do_re),
      .do_im  (gold_do_im)
`ifdef INTERNAL_ASSERTS
      `include "ports_a.vh"
`endif
   );

   gate_top i_gate (
      .clock  (clock),
      .reset  (reset),
      .di_en  (di_en),
      .di_re  (di_re),
      .di_im  (di_im),
      .do_en  (gate_do_en),
      .do_re  (gate_do_re),
      .do_im  (gate_do_im)
`ifdef INTERNAL_ASSERTS
      `include "ports_b.vh"
`endif
   );

   always @(posedge clock) begin
      assert(gold_do_en == gate_do_en);
      assert(gold_do_re == gate_do_re);
      assert(gold_do_im == gate_do_im);
`ifdef INTERNAL_ASSERTS
      `include "asserts.vh"
`endif
   end

endmodule
`default_nettype wire
