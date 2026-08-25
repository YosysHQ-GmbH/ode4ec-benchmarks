`default_nettype none

module miter
  #(parameter WIDTH = 8, parameter DEPTH = 4)
   (
    input wire                     Clk,
    input wire [$clog2(DEPTH)-1:0] Addr,
    input wire                     WrEna,
    input wire [WIDTH-1:0]         WrData
   );

   wire [WIDTH-1:0] gold_RdData, gate_RdData;

`ifdef INTERNAL_ASSERTS
   `include "decls.vh"
`endif

   gold_top i_gold (
      .Clk   (Clk),
      .Addr  (Addr),
      .WrEna (WrEna),
      .WrData(WrData),
      .RdData(gold_RdData)
`ifdef INTERNAL_ASSERTS
      `include "ports_a.vh"
`endif
   );

   gate_top i_gate (
      .Clk   (Clk),
      .Addr  (Addr),
      .WrEna (WrEna),
      .WrData(WrData),
      .RdData(gate_RdData)
`ifdef INTERNAL_ASSERTS
      `include "ports_b.vh"
`endif
   );

   always @(posedge Clk) begin
      assert(gold_RdData == gate_RdData);
`ifdef INTERNAL_ASSERTS
      `include "asserts.vh"
`endif
   end

endmodule
`default_nettype wire
