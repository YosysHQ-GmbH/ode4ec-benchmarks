`default_nettype none

module miter
  #(parameter WIDTH = 8, parameter DEPTH = 4)
   (
    input wire             Clk,
    input wire             Rst,
    input wire [WIDTH-1:0] In_Data,
    input wire             In_Valid,
    input wire             Out_Ready
   );

   wire gold_In_Ready, gate_In_Ready;
   wire [$clog2(DEPTH+1)-1:0] gold_In_Level, gate_In_Level;
   wire gold_Out_Valid, gate_Out_Valid;
   wire [WIDTH-1:0] gold_Out_Data, gate_Out_Data;
   wire [$clog2(DEPTH+1)-1:0] gold_Out_Level, gate_Out_Level;
   wire gold_Full, gate_Full;
   wire gold_Empty, gate_Empty;

`ifdef INTERNAL_ASSERTS
   `include "decls.vh"
`endif

   gold_top i_gold (
      .Clk      (Clk),
      .Rst      (Rst),
      .In_Data  (In_Data),
      .In_Valid (In_Valid),
      .In_Ready (gold_In_Ready),
      .In_Level (gold_In_Level),
      .Out_Data (gold_Out_Data),
      .Out_Valid(gold_Out_Valid),
      .Out_Ready(Out_Ready),
      .Out_Level(gold_Out_Level),
      .Full     (gold_Full),
      .AlmFull  (),
      .Empty    (gold_Empty),
      .AlmEmpty ()
`ifdef INTERNAL_ASSERTS
      `include "ports_a.vh"
`endif
   );

   gate_top i_gate (
      .Clk      (Clk),
      .Rst      (Rst),
      .In_Data  (In_Data),
      .In_Valid (In_Valid),
      .In_Ready (gate_In_Ready),
      .In_Level (gate_In_Level),
      .Out_Data (gate_Out_Data),
      .Out_Valid(gate_Out_Valid),
      .Out_Ready(Out_Ready),
      .Out_Level(gate_Out_Level),
      .Full     (gate_Full),
      .AlmFull  (),
      .Empty    (gate_Empty),
      .AlmEmpty ()
`ifdef INTERNAL_ASSERTS
      `include "ports_b.vh"
`endif
   );

   always @(posedge Clk) begin
      assert(gold_In_Ready == gate_In_Ready);
      assert(gold_In_Level == gate_In_Level);
      assert(gold_Out_Valid == gate_Out_Valid);
      assert(gold_Out_Data == gate_Out_Data);
      assert(gold_Out_Level == gate_Out_Level);
      assert(gold_Full == gate_Full);
      assert(gold_Empty == gate_Empty);
`ifdef INTERNAL_ASSERTS
      `include "asserts.vh"
`endif
   end

endmodule
`default_nettype wire
