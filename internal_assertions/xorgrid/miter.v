`default_nettype none

// Fixed regardless of swept grid SIZE: I/O/C are pinned constants for the
// whole xorgrid sweep (see Makefile), so this wrapper never needs
// regeneration per SIZE -- only the generated RTL underneath gold_top/
// gate_top grows.
module miter
  #(parameter I = 32,
    parameter O = 32,
    parameter C = 16)
   (
    input wire          clk,
    input wire          rst,
    input wire [I-1:0]  in,
    input wire [C-1:0]  ctrl
   );

   wire [O-1:0] out_a;
   wire [O-1:0] out_b;

`ifdef INTERNAL_ASSERTS
   `include "decls.vh"
`endif

   gold_top dut_a (
      .clk (clk),
      .rst (rst),
      .in  (in),
      .ctrl(ctrl),
      .out (out_a)
`ifdef INTERNAL_ASSERTS
      `include "ports_a.vh"
`endif
   );

   gate_top dut_b (
      .clk (clk),
      .rst (rst),
      .in  (in),
      .ctrl(ctrl),
      .out (out_b)
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
`default_nettype wire
