`default_nettype none
module de0_nano_clock_gen
  (input wire i_clk,
   input wire  i_rst,
   output wire o_clk,
   output wire o_rst);

   assign o_rst = i_rst;
   assign o_clk = i_clk;

endmodule
