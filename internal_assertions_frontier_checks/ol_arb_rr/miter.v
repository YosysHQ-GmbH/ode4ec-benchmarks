`default_nettype none

module miter
  #(parameter WIDTH = 8)
   (
    input wire             Clk,
    input wire             Rst,
    input wire [WIDTH-1:0] In_Req,
    input wire             Out_Ready
   );

   wire [WIDTH-1:0] gold_Out_Grant, gate_Out_Grant;
   wire             gold_Out_Valid, gate_Out_Valid;

`ifdef INTERNAL_ASSERTS
   `include "decls.vh"
`endif

   gold_top i_gold (
      .Clk      (Clk),
      .Rst      (Rst),
      .In_Req   (In_Req),
      .Out_Grant(gold_Out_Grant),
      .Out_Ready(Out_Ready),
      .Out_Valid(gold_Out_Valid)
`ifdef INTERNAL_ASSERTS
      `include "ports_a.vh"
`endif
   );

   gate_top i_gate (
      .Clk      (Clk),
      .Rst      (Rst),
      .In_Req   (In_Req),
      .Out_Grant(gate_Out_Grant),
      .Out_Ready(Out_Ready),
      .Out_Valid(gate_Out_Valid)
`ifdef INTERNAL_ASSERTS
      `include "ports_b.vh"
`endif
   );

   always @(posedge Clk) begin
      assert(gold_Out_Grant == gate_Out_Grant);
      assert(gold_Out_Valid == gate_Out_Valid);
`ifdef INTERNAL_ASSERTS
      `include "asserts.vh"
`endif
   end

endmodule
`default_nettype wire
