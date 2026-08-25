`default_nettype none

module miter
  #(parameter WIDTH = 8, parameter DEPTH = 4)
   (
    input wire                     Clk,
    input wire [$clog2(DEPTH)-1:0] Wr_Addr,
    input wire                     Wr_Ena,
    input wire [WIDTH-1:0]         Wr_Data,
    input wire [$clog2(DEPTH)-1:0] Rd_Addr,
    input wire                     Rd_Ena
   );

   wire [WIDTH-1:0] gold_Rd_Data, gate_Rd_Data;

`ifdef INTERNAL_ASSERTS
   `include "decls.vh"
`endif

   gold_top i_gold (
      .Clk    (Clk),
      .Wr_Addr(Wr_Addr),
      .Wr_Ena (Wr_Ena),
      .Wr_Data(Wr_Data),
      .Rd_Addr(Rd_Addr),
      .Rd_Ena (Rd_Ena),
      .Rd_Data(gold_Rd_Data)
`ifdef INTERNAL_ASSERTS
      `include "ports_a.vh"
`endif
   );

   gate_top i_gate (
      .Clk    (Clk),
      .Wr_Addr(Wr_Addr),
      .Wr_Ena (Wr_Ena),
      .Wr_Data(Wr_Data),
      .Rd_Addr(Rd_Addr),
      .Rd_Ena (Rd_Ena),
      .Rd_Data(gate_Rd_Data)
`ifdef INTERNAL_ASSERTS
      `include "ports_b.vh"
`endif
   );

   always @(posedge Clk) begin
      assert(gold_Rd_Data == gate_Rd_Data);
`ifdef INTERNAL_ASSERTS
      `include "asserts.vh"
`endif
   end

endmodule
`default_nettype wire
