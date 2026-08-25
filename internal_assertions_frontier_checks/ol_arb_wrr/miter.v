`default_nettype none

module miter
  #(parameter WIDTH = 4, parameter GRANT = 8)
   (
    input wire                   Clk,
    input wire                   Rst,
    input wire [WIDTH*GRANT-1:0] Weights,
    input wire                   In_Valid,
    input wire [GRANT-1:0]       In_Req
   );

   wire gold_Out_Valid, gate_Out_Valid;
   wire [GRANT-1:0] gold_Out_Grant, gate_Out_Grant;

`ifdef INTERNAL_ASSERTS
   `include "decls.vh"
`endif

   gold_top i_gold (
      .Clk      (Clk),
      .Rst      (Rst),
      .Weights  (Weights),
      .In_Valid (In_Valid),
      .In_Req   (In_Req),
      .Out_Valid(gold_Out_Valid),
      .Out_Grant(gold_Out_Grant)
`ifdef INTERNAL_ASSERTS
      `include "ports_a.vh"
`endif
   );

   gate_top i_gate (
      .Clk      (Clk),
      .Rst      (Rst),
      .Weights  (Weights),
      .In_Valid (In_Valid),
      .In_Req   (In_Req),
      .Out_Valid(gate_Out_Valid),
      .Out_Grant(gate_Out_Grant)
`ifdef INTERNAL_ASSERTS
      `include "ports_b.vh"
`endif
   );

   always @(posedge Clk) begin
      assert(gold_Out_Valid == gate_Out_Valid);
      assert(gold_Out_Grant == gate_Out_Grant);
`ifdef INTERNAL_ASSERTS
      `include "asserts.vh"
`endif
   end

endmodule
`default_nettype wire
