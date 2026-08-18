`default_nettype none

module miter (
   input wire  i_clk,
   input wire  i_rst_n
);

   wire q_a, uart_txd_a;
   wire q_b, uart_txd_b;

`ifdef INTERNAL_ASSERTS
   `include "decls.vh"
`endif

   gold_top dut_a (
      .i_clk    (i_clk),
      .i_rst_n  (i_rst_n),
      .q        (q_a),
      .uart_txd (uart_txd_a)
`ifdef INTERNAL_ASSERTS
      `include "ports_a.vh"
`endif
   );

   gate_top dut_b (
      .i_clk    (i_clk),
      .i_rst_n  (i_rst_n),
      .q        (q_b),
      .uart_txd (uart_txd_b)
`ifdef INTERNAL_ASSERTS
      `include "ports_b.vh"
`endif
   );

   always @(posedge i_clk) begin
      assert(q_a == q_b);
      assert(uart_txd_a == uart_txd_b);
`ifdef INTERNAL_ASSERTS
      `include "asserts.vh"
`endif
   end

endmodule
`default_nettype wire
