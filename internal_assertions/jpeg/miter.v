`default_nettype none

module miter
   (
    input wire       clk,
    input wire       ena,
    input wire       rst,
    input wire       dstrb,
    input wire [7:0] din,
    input wire [7:0] qnt_val
   );

   wire [5:0]  qnt_cnt_a;
   wire [3:0]  size_a;
   wire [3:0]  rlen_a;
   wire [11:0] amp_a;
   wire        douten_a;

   wire [5:0]  qnt_cnt_b;
   wire [3:0]  size_b;
   wire [3:0]  rlen_b;
   wire [11:0] amp_b;
   wire        douten_b;

   `include "internal_helper_decls.vh"

   gold_top dut_a (
      .clk     (clk),
      .ena     (ena),
      .rst     (rst),
      .dstrb   (dstrb),
      .din     (din),
      .qnt_val (qnt_val),
      .qnt_cnt (qnt_cnt_a),
      .size    (size_a),
      .rlen    (rlen_a),
      .amp     (amp_a),
      .douten  (douten_a)
      `include "internal_helper_ports_a.vh"
   );

   gate_top dut_b (
      .clk     (clk),
      .ena     (ena),
      .rst     (rst),
      .dstrb   (dstrb),
      .din     (din),
      .qnt_val (qnt_val),
      .qnt_cnt (qnt_cnt_b),
      .size    (size_b),
      .rlen    (rlen_b),
      .amp     (amp_b),
      .douten  (douten_b)
      `include "internal_helper_ports_b.vh"
   );

   always @(posedge clk) begin

      assert(qnt_cnt_a == qnt_cnt_b);
      assert(size_a    == size_b);
      assert(rlen_a    == rlen_b);
      assert(amp_a     == amp_b);
      assert(douten_a  == douten_b);

`ifdef INTERNAL_ASSERTS
      `include "internal_helper_asserts.vh"
`endif
   end

endmodule
`default_nettype wire
