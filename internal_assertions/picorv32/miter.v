`default_nettype none

module miter
   (
    input wire        clk,
    input wire        resetn,
    input wire         mem_ready,
    input wire [31:0]  mem_rdata,
    input wire         pcpi_wr,
    input wire [31:0]  pcpi_rd,
    input wire         pcpi_wait,
    input wire         pcpi_ready,
    input wire [31:0]  irq
   );

   wire        trap_a;
   wire        mem_valid_a;
   wire        mem_instr_a;
   wire [31:0] mem_addr_a;
   wire [31:0] mem_wdata_a;
   wire [3:0]  mem_wstrb_a;
   wire        mem_la_read_a;
   wire        mem_la_write_a;
   wire [31:0] mem_la_addr_a;
   wire [31:0] mem_la_wdata_a;
   wire [3:0]  mem_la_wstrb_a;
   wire        pcpi_valid_a;
   wire [31:0] pcpi_insn_a;
   wire [31:0] pcpi_rs1_a;
   wire [31:0] pcpi_rs2_a;
   wire [31:0] eoi_a;

   wire        trap_b;
   wire        mem_valid_b;
   wire        mem_instr_b;
   wire [31:0] mem_addr_b;
   wire [31:0] mem_wdata_b;
   wire [3:0]  mem_wstrb_b;
   wire        mem_la_read_b;
   wire        mem_la_write_b;
   wire [31:0] mem_la_addr_b;
   wire [31:0] mem_la_wdata_b;
   wire [3:0]  mem_la_wstrb_b;
   wire        pcpi_valid_b;
   wire [31:0] pcpi_insn_b;
   wire [31:0] pcpi_rs1_b;
   wire [31:0] pcpi_rs2_b;
   wire [31:0] eoi_b;

   `include "internal_helper_decls.vh"

   gold_top dut_a (
      .clk          (clk),
      .resetn       (resetn),
      .trap         (trap_a),
      .mem_valid    (mem_valid_a),
      .mem_instr    (mem_instr_a),
      .mem_ready    (mem_ready),
      .mem_addr     (mem_addr_a),
      .mem_wdata    (mem_wdata_a),
      .mem_wstrb    (mem_wstrb_a),
      .mem_rdata    (mem_rdata),
      .mem_la_read  (mem_la_read_a),
      .mem_la_write (mem_la_write_a),
      .mem_la_addr  (mem_la_addr_a),
      .mem_la_wdata (mem_la_wdata_a),
      .mem_la_wstrb (mem_la_wstrb_a),
      .pcpi_valid   (pcpi_valid_a),
      .pcpi_insn    (pcpi_insn_a),
      .pcpi_rs1     (pcpi_rs1_a),
      .pcpi_rs2     (pcpi_rs2_a),
      .pcpi_wr      (pcpi_wr),
      .pcpi_rd      (pcpi_rd),
      .pcpi_wait    (pcpi_wait),
      .pcpi_ready   (pcpi_ready),
      .irq          (irq),
      .eoi          (eoi_a)
      `include "internal_helper_ports_a.vh"
   );

   gate_top dut_b (
      .clk          (clk),
      .resetn       (resetn),
      .trap         (trap_b),
      .mem_valid    (mem_valid_b),
      .mem_instr    (mem_instr_b),
      .mem_ready    (mem_ready),
      .mem_addr     (mem_addr_b),
      .mem_wdata    (mem_wdata_b),
      .mem_wstrb    (mem_wstrb_b),
      .mem_rdata    (mem_rdata),
      .mem_la_read  (mem_la_read_b),
      .mem_la_write (mem_la_write_b),
      .mem_la_addr  (mem_la_addr_b),
      .mem_la_wdata (mem_la_wdata_b),
      .mem_la_wstrb (mem_la_wstrb_b),
      .pcpi_valid   (pcpi_valid_b),
      .pcpi_insn    (pcpi_insn_b),
      .pcpi_rs1     (pcpi_rs1_b),
      .pcpi_rs2     (pcpi_rs2_b),
      .pcpi_wr      (pcpi_wr),
      .pcpi_rd      (pcpi_rd),
      .pcpi_wait    (pcpi_wait),
      .pcpi_ready   (pcpi_ready),
      .irq          (irq),
      .eoi          (eoi_b)
      `include "internal_helper_ports_b.vh"
   );

   always @(posedge clk) begin
      assert(trap_a          == trap_b);
      assert(mem_valid_a     == mem_valid_b);
      assert(mem_instr_a     == mem_instr_b);
      assert(mem_addr_a      == mem_addr_b);
      assert(mem_wdata_a     == mem_wdata_b);
      assert(mem_wstrb_a     == mem_wstrb_b);
      assert(mem_la_read_a   == mem_la_read_b);
      assert(mem_la_write_a  == mem_la_write_b);
      assert(mem_la_addr_a   == mem_la_addr_b);
      assert(mem_la_wdata_a  == mem_la_wdata_b);
      assert(mem_la_wstrb_a  == mem_la_wstrb_b);
      assert(pcpi_valid_a    == pcpi_valid_b);
      assert(pcpi_insn_a     == pcpi_insn_b);
      assert(pcpi_rs1_a      == pcpi_rs1_b);
      assert(pcpi_rs2_a      == pcpi_rs2_b);
      assert(eoi_a           == eoi_b);
`ifdef INTERNAL_ASSERTS
      `include "internal_helper_asserts.vh"
`endif
   end

endmodule
`default_nettype wire
