`default_nettype none

module miter
  #(parameter        WITH_CSR = 1,
    parameter        W = 1,
    parameter        B = W-1,
    parameter        PRE_REGISTER = 1,
    parameter        RESET_STRATEGY = "MINI",
    parameter        RESET_PC = 32'd0,
    parameter [0:0]  DEBUG = 1'b0,
    parameter [0:0]  MDU = 1'b0,
    parameter [0:0]  COMPRESSED = 0,
    parameter [0:0]  ALIGN = COMPRESSED)
   (
    input wire       clk,
    input wire       i_rst,
    input wire       i_timer_irq,
    input wire       i_rf_ready,
    input wire [B:0] i_rdata0,
    input wire [B:0] i_rdata1,
    input wire [31:0] i_ibus_rdt,
    input wire       i_ibus_ack,
    input wire [31:0] i_dbus_rdt,
    input wire       i_dbus_ack,
    input wire       i_ext_ready,
    input wire [31:0] i_ext_rd
   );

`ifdef RISCV_FORMAL
   wire               rvfi_valid_a;
   wire [63:0]        rvfi_order_a;
   wire [31:0]        rvfi_insn_a;
   wire               rvfi_trap_a;
   wire               rvfi_halt_a;
   wire               rvfi_intr_a;
   wire [1:0]         rvfi_mode_a;
   wire [1:0]         rvfi_ixl_a;
   wire [4:0]         rvfi_rs1_addr_a;
   wire [4:0]         rvfi_rs2_addr_a;
   wire [31:0]        rvfi_rs1_rdata_a;
   wire [31:0]        rvfi_rs2_rdata_a;
   wire [4:0]         rvfi_rd_addr_a;
   wire [31:0]        rvfi_rd_wdata_a;
   wire [31:0]        rvfi_pc_rdata_a;
   wire [31:0]        rvfi_pc_wdata_a;
   wire [31:0]        rvfi_mem_addr_a;
   wire [3:0]         rvfi_mem_rmask_a;
   wire [3:0]         rvfi_mem_wmask_a;
   wire [31:0]        rvfi_mem_rdata_a;
   wire [31:0]        rvfi_mem_wdata_a;
`endif
   wire               o_rf_rreq_a;
   wire               o_rf_wreq_a;
   wire [4+WITH_CSR:0] o_wreg0_a;
   wire [4+WITH_CSR:0] o_wreg1_a;
   wire               o_wen0_a;
   wire               o_wen1_a;
   wire [B:0]         o_wdata0_a;
   wire [B:0]         o_wdata1_a;
   wire [4+WITH_CSR:0] o_rreg0_a;
   wire [4+WITH_CSR:0] o_rreg1_a;
   wire [31:0]        o_ibus_adr_a;
   wire               o_ibus_cyc_a;
   wire [31:0]        o_dbus_adr_a;
   wire [31:0]        o_dbus_dat_a;
   wire [3:0]         o_dbus_sel_a;
   wire               o_dbus_we_a;
   wire               o_dbus_cyc_a;
   wire [2:0]         o_ext_funct3_a;
   wire [31:0]        o_ext_rs1_a;
   wire [31:0]        o_ext_rs2_a;
   wire               o_mdu_valid_a;

`ifdef RISCV_FORMAL
   wire               rvfi_valid_b;
   wire [63:0]        rvfi_order_b;
   wire [31:0]        rvfi_insn_b;
   wire               rvfi_trap_b;
   wire               rvfi_halt_b;
   wire               rvfi_intr_b;
   wire [1:0]         rvfi_mode_b;
   wire [1:0]         rvfi_ixl_b;
   wire [4:0]         rvfi_rs1_addr_b;
   wire [4:0]         rvfi_rs2_addr_b;
   wire [31:0]        rvfi_rs1_rdata_b;
   wire [31:0]        rvfi_rs2_rdata_b;
   wire [4:0]         rvfi_rd_addr_b;
   wire [31:0]        rvfi_rd_wdata_b;
   wire [31:0]        rvfi_pc_rdata_b;
   wire [31:0]        rvfi_pc_wdata_b;
   wire [31:0]        rvfi_mem_addr_b;
   wire [3:0]         rvfi_mem_rmask_b;
   wire [3:0]         rvfi_mem_wmask_b;
   wire [31:0]        rvfi_mem_rdata_b;
   wire [31:0]        rvfi_mem_wdata_b;
`endif
   wire               o_rf_rreq_b;
   wire               o_rf_wreq_b;
   wire [4+WITH_CSR:0] o_wreg0_b;
   wire [4+WITH_CSR:0] o_wreg1_b;
   wire               o_wen0_b;
   wire               o_wen1_b;
   wire [B:0]         o_wdata0_b;
   wire [B:0]         o_wdata1_b;
   wire [4+WITH_CSR:0] o_rreg0_b;
   wire [4+WITH_CSR:0] o_rreg1_b;
   wire [31:0]        o_ibus_adr_b;
   wire               o_ibus_cyc_b;
   wire [31:0]        o_dbus_adr_b;
   wire [31:0]        o_dbus_dat_b;
   wire [3:0]         o_dbus_sel_b;
   wire               o_dbus_we_b;
   wire               o_dbus_cyc_b;
   wire [2:0]         o_ext_funct3_b;
   wire [31:0]        o_ext_rs1_b;
   wire [31:0]        o_ext_rs2_b;
   wire               o_mdu_valid_b;

`ifdef INTERNAL_ASSERTS 
   `include "decls.vh"
`endif


   gold_top dut_a (
      .clk          (clk),
      .i_rst        (i_rst),
      .i_timer_irq  (i_timer_irq),
`ifdef RISCV_FORMAL
      .rvfi_valid   (rvfi_valid_a),
      .rvfi_order   (rvfi_order_a),
      .rvfi_insn    (rvfi_insn_a),
      .rvfi_trap    (rvfi_trap_a),
      .rvfi_halt    (rvfi_halt_a),
      .rvfi_intr    (rvfi_intr_a),
      .rvfi_mode    (rvfi_mode_a),
      .rvfi_ixl     (rvfi_ixl_a),
      .rvfi_rs1_addr(rvfi_rs1_addr_a),
      .rvfi_rs2_addr(rvfi_rs2_addr_a),
      .rvfi_rs1_rdata(rvfi_rs1_rdata_a),
      .rvfi_rs2_rdata(rvfi_rs2_rdata_a),
      .rvfi_rd_addr (rvfi_rd_addr_a),
      .rvfi_rd_wdata(rvfi_rd_wdata_a),
      .rvfi_pc_rdata(rvfi_pc_rdata_a),
      .rvfi_pc_wdata(rvfi_pc_wdata_a),
      .rvfi_mem_addr(rvfi_mem_addr_a),
      .rvfi_mem_rmask(rvfi_mem_rmask_a),
      .rvfi_mem_wmask(rvfi_mem_wmask_a),
      .rvfi_mem_rdata(rvfi_mem_rdata_a),
      .rvfi_mem_wdata(rvfi_mem_wdata_a),
`endif
      .o_rf_rreq    (o_rf_rreq_a),
      .o_rf_wreq    (o_rf_wreq_a),
      .i_rf_ready   (i_rf_ready),
      .o_wreg0      (o_wreg0_a),
      .o_wreg1      (o_wreg1_a),
      .o_wen0       (o_wen0_a),
      .o_wen1       (o_wen1_a),
      .o_wdata0     (o_wdata0_a),
      .o_wdata1     (o_wdata1_a),
      .o_rreg0      (o_rreg0_a),
      .o_rreg1      (o_rreg1_a),
      .i_rdata0     (i_rdata0),
      .i_rdata1     (i_rdata1),
      .o_ibus_adr   (o_ibus_adr_a),
      .o_ibus_cyc   (o_ibus_cyc_a),
      .i_ibus_rdt   (i_ibus_rdt),
      .i_ibus_ack   (i_ibus_ack),
      .o_dbus_adr   (o_dbus_adr_a),
      .o_dbus_dat   (o_dbus_dat_a),
      .o_dbus_sel   (o_dbus_sel_a),
      .o_dbus_we    (o_dbus_we_a),
      .o_dbus_cyc   (o_dbus_cyc_a),
      .i_dbus_rdt   (i_dbus_rdt),
      .i_dbus_ack   (i_dbus_ack),
      .o_ext_funct3 (o_ext_funct3_a),
      .i_ext_ready  (i_ext_ready),
      .i_ext_rd     (i_ext_rd),
      .o_ext_rs1    (o_ext_rs1_a),
      .o_ext_rs2    (o_ext_rs2_a),
      .o_mdu_valid  (o_mdu_valid_a)
`ifdef INTERNAL_ASSERTS 
      `include "ports_a.vh"
`endif
   );

   gate_top dut_b (
      .clk          (clk),
      .i_rst        (i_rst),
      .i_timer_irq  (i_timer_irq),
`ifdef RISCV_FORMAL
      .rvfi_valid   (rvfi_valid_b),
      .rvfi_order   (rvfi_order_b),
      .rvfi_insn    (rvfi_insn_b),
      .rvfi_trap    (rvfi_trap_b),
      .rvfi_halt    (rvfi_halt_b),
      .rvfi_intr    (rvfi_intr_b),
      .rvfi_mode    (rvfi_mode_b),
      .rvfi_ixl     (rvfi_ixl_b),
      .rvfi_rs1_addr(rvfi_rs1_addr_b),
      .rvfi_rs2_addr(rvfi_rs2_addr_b),
      .rvfi_rs1_rdata(rvfi_rs1_rdata_b),
      .rvfi_rs2_rdata(rvfi_rs2_rdata_b),
      .rvfi_rd_addr (rvfi_rd_addr_b),
      .rvfi_rd_wdata(rvfi_rd_wdata_b),
      .rvfi_pc_rdata(rvfi_pc_rdata_b),
      .rvfi_pc_wdata(rvfi_pc_wdata_b),
      .rvfi_mem_addr(rvfi_mem_addr_b),
      .rvfi_mem_rmask(rvfi_mem_rmask_b),
      .rvfi_mem_wmask(rvfi_mem_wmask_b),
      .rvfi_mem_rdata(rvfi_mem_rdata_b),
      .rvfi_mem_wdata(rvfi_mem_wdata_b),
`endif
      .o_rf_rreq    (o_rf_rreq_b),
      .o_rf_wreq    (o_rf_wreq_b),
      .i_rf_ready   (i_rf_ready),
      .o_wreg0      (o_wreg0_b),
      .o_wreg1      (o_wreg1_b),
      .o_wen0       (o_wen0_b),
      .o_wen1       (o_wen1_b),
      .o_wdata0     (o_wdata0_b),
      .o_wdata1     (o_wdata1_b),
      .o_rreg0      (o_rreg0_b),
      .o_rreg1      (o_rreg1_b),
      .i_rdata0     (i_rdata0),
      .i_rdata1     (i_rdata1),
      .o_ibus_adr   (o_ibus_adr_b),
      .o_ibus_cyc   (o_ibus_cyc_b),
      .i_ibus_rdt   (i_ibus_rdt),
      .i_ibus_ack   (i_ibus_ack),
      .o_dbus_adr   (o_dbus_adr_b),
      .o_dbus_dat   (o_dbus_dat_b),
      .o_dbus_sel   (o_dbus_sel_b),
      .o_dbus_we    (o_dbus_we_b),
      .o_dbus_cyc   (o_dbus_cyc_b),
      .i_dbus_rdt   (i_dbus_rdt),
      .i_dbus_ack   (i_dbus_ack),
      .o_ext_funct3 (o_ext_funct3_b),
      .i_ext_ready  (i_ext_ready),
      .i_ext_rd     (i_ext_rd),
      .o_ext_rs1    (o_ext_rs1_b),
      .o_ext_rs2    (o_ext_rs2_b),
      .o_mdu_valid  (o_mdu_valid_b)
`ifdef INTERNAL_ASSERTS 
      `include "ports_b.vh"
`endif
   );

   always @(posedge clk) begin
      assert(o_rf_rreq_a    == o_rf_rreq_b);
      assert(o_rf_wreq_a    == o_rf_wreq_b);
      assert(o_wreg0_a      == o_wreg0_b);
      assert(o_wreg1_a      == o_wreg1_b);
      assert(o_wen0_a       == o_wen0_b);
      assert(o_wen1_a       == o_wen1_b);
      assert(o_wdata0_a     == o_wdata0_b);
      assert(o_wdata1_a     == o_wdata1_b);
      assert(o_rreg0_a      == o_rreg0_b);
      assert(o_rreg1_a      == o_rreg1_b);
      assert(o_ibus_adr_a   == o_ibus_adr_b);
      assert(o_ibus_cyc_a   == o_ibus_cyc_b);
      assert(o_dbus_adr_a   == o_dbus_adr_b);
      assert(o_dbus_dat_a   == o_dbus_dat_b);
      assert(o_dbus_sel_a   == o_dbus_sel_b);
      assert(o_dbus_we_a    == o_dbus_we_b);
      assert(o_dbus_cyc_a   == o_dbus_cyc_b);
      assert(o_ext_funct3_a == o_ext_funct3_b);
      assert(o_ext_rs1_a    == o_ext_rs1_b);
      assert(o_ext_rs2_a    == o_ext_rs2_b);
      assert(o_mdu_valid_a  == o_mdu_valid_b);
`ifdef RISCV_FORMAL
      assert(rvfi_valid_a     == rvfi_valid_b);
      assert(rvfi_order_a     == rvfi_order_b);
      assert(rvfi_insn_a      == rvfi_insn_b);
      assert(rvfi_trap_a      == rvfi_trap_b);
      assert(rvfi_halt_a      == rvfi_halt_b);
      assert(rvfi_intr_a      == rvfi_intr_b);
      assert(rvfi_mode_a      == rvfi_mode_b);
      assert(rvfi_ixl_a       == rvfi_ixl_b);
      assert(rvfi_rs1_addr_a  == rvfi_rs1_addr_b);
      assert(rvfi_rs2_addr_a  == rvfi_rs2_addr_b);
      assert(rvfi_rs1_rdata_a == rvfi_rs1_rdata_b);
      assert(rvfi_rs2_rdata_a == rvfi_rs2_rdata_b);
      assert(rvfi_rd_addr_a   == rvfi_rd_addr_b);
      assert(rvfi_rd_wdata_a  == rvfi_rd_wdata_b);
      assert(rvfi_pc_rdata_a  == rvfi_pc_rdata_b);
      assert(rvfi_pc_wdata_a  == rvfi_pc_wdata_b);
      assert(rvfi_mem_addr_a  == rvfi_mem_addr_b);
      assert(rvfi_mem_rmask_a == rvfi_mem_rmask_b);
      assert(rvfi_mem_wmask_a == rvfi_mem_wmask_b);
      assert(rvfi_mem_rdata_a == rvfi_mem_rdata_b);
      assert(rvfi_mem_wdata_a == rvfi_mem_wdata_b);
`endif
`ifdef INTERNAL_ASSERTS 
      `include "asserts.vh"
`endif
   end
   
endmodule
`default_nettype wire
