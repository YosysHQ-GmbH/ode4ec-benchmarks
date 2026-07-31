`default_nettype none

module miter
  #(parameter I = 16,
    parameter O = 16,
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
