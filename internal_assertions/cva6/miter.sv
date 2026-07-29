`include "rvfi_types.svh"
`include "cvxif_types.svh"

module miter 
  import ariane_pkg::*;
#(
    parameter config_pkg::cva6_cfg_t CVA6Cfg = build_config_pkg::build_config(
        cva6_config_pkg::cva6_cfg
    ),

    parameter type rvfi_probes_instr_t = `RVFI_PROBES_INSTR_T(CVA6Cfg),
    parameter type rvfi_probes_csr_t = `RVFI_PROBES_CSR_T(CVA6Cfg),
    parameter type rvfi_probes_t = struct packed {
      rvfi_probes_csr_t   csr;
      rvfi_probes_instr_t instr;
    },

    parameter type axi_ar_chan_t = struct packed {
      logic [CVA6Cfg.AxiIdWidth-1:0]   id;
      logic [CVA6Cfg.AxiAddrWidth-1:0] addr;
      axi_pkg::len_t                   len;
      axi_pkg::size_t                  size;
      axi_pkg::burst_t                 burst;
      logic                            lock;
      axi_pkg::cache_t                 cache;
      axi_pkg::prot_t                  prot;
      axi_pkg::qos_t                   qos;
      axi_pkg::region_t                region;
      logic [CVA6Cfg.AxiUserWidth-1:0] user;
    },
    parameter type axi_aw_chan_t = struct packed {
      logic [CVA6Cfg.AxiIdWidth-1:0]   id;
      logic [CVA6Cfg.AxiAddrWidth-1:0] addr;
      axi_pkg::len_t                   len;
      axi_pkg::size_t                  size;
      axi_pkg::burst_t                 burst;
      logic                            lock;
      axi_pkg::cache_t                 cache;
      axi_pkg::prot_t                  prot;
      axi_pkg::qos_t                   qos;
      axi_pkg::region_t                region;
      axi_pkg::atop_t                  atop;
      logic [CVA6Cfg.AxiUserWidth-1:0] user;
    },
    parameter type axi_w_chan_t = struct packed {
      logic [CVA6Cfg.AxiDataWidth-1:0]     data;
      logic [(CVA6Cfg.AxiDataWidth/8)-1:0] strb;
      logic                                last;
      logic [CVA6Cfg.AxiUserWidth-1:0]     user;
    },
    parameter type b_chan_t = struct packed {
      logic [CVA6Cfg.AxiIdWidth-1:0]   id;
      axi_pkg::resp_t                  resp;
      logic [CVA6Cfg.AxiUserWidth-1:0] user;
    },
    parameter type r_chan_t = struct packed {
      logic [CVA6Cfg.AxiIdWidth-1:0]   id;
      logic [CVA6Cfg.AxiDataWidth-1:0] data;
      axi_pkg::resp_t                  resp;
      logic                            last;
      logic [CVA6Cfg.AxiUserWidth-1:0] user;
    },
    parameter type noc_req_t = struct packed {
      axi_aw_chan_t aw;
      logic         aw_valid;
      axi_w_chan_t  w;
      logic         w_valid;
      logic         b_ready;
      axi_ar_chan_t ar;
      logic         ar_valid;
      logic         r_ready;
    },
    parameter type noc_resp_t = struct packed {
      logic    aw_ready;
      logic    ar_ready;
      logic    w_ready;
      logic    b_valid;
      b_chan_t b;
      logic    r_valid;
      r_chan_t r;
    },

    parameter type readregflags_t = `READREGFLAGS_T(CVA6Cfg),
    parameter type writeregflags_t = `WRITEREGFLAGS_T(CVA6Cfg),
    parameter type id_t = `ID_T(CVA6Cfg),
    parameter type hartid_t = `HARTID_T(CVA6Cfg),
    parameter type x_compressed_req_t = `X_COMPRESSED_REQ_T(CVA6Cfg, hartid_t),
    parameter type x_compressed_resp_t = `X_COMPRESSED_RESP_T(CVA6Cfg),
    parameter type x_issue_req_t = `X_ISSUE_REQ_T(CVA6Cfg, hartid_t, id_t),
    parameter type x_issue_resp_t = `X_ISSUE_RESP_T(CVA6Cfg, writeregflags_t, readregflags_t),
    parameter type x_register_t = `X_REGISTER_T(CVA6Cfg, hartid_t, id_t, readregflags_t),
    parameter type x_commit_t = `X_COMMIT_T(CVA6Cfg, hartid_t, id_t),
    parameter type x_result_t = `X_RESULT_T(CVA6Cfg, hartid_t, id_t, writeregflags_t),
    parameter type cvxif_req_t = `CVXIF_REQ_T(CVA6Cfg, x_compressed_req_t, x_issue_req_t, x_register_t, x_commit_t),
    parameter type cvxif_resp_t = `CVXIF_RESP_T(CVA6Cfg, x_compressed_resp_t, x_issue_resp_t, x_result_t)

) (
    input logic clk_i,
    input logic rst_ni,
    input logic [CVA6Cfg.VLEN-1:0] boot_addr_i,
    input logic [CVA6Cfg.XLEN-1:0] hart_id_i,
    input logic [1:0] irq_i,
    input logic ipi_i,
    input logic time_irq_i,
    input logic debug_req_i,
    
    input cvxif_resp_t cvxif_resp_i,
    input noc_resp_t   noc_resp_i
);

    rvfi_probes_t gold_rvfi_probes_o;
    cvxif_req_t   gold_cvxif_req_o;
    noc_req_t     gold_noc_req_o;

    rvfi_probes_t gate_rvfi_probes_o;
    cvxif_req_t   gate_cvxif_req_o;
    noc_req_t     gate_noc_req_o;

    `include "internal_helper_decls.vh"

    gold_top i_gold (
        .clk_i         (clk_i),
        .rst_ni        (rst_ni),
        .boot_addr_i   (boot_addr_i),
        .hart_id_i     (hart_id_i),
        .irq_i         (irq_i),
        .ipi_i         (ipi_i),
        .time_irq_i    (time_irq_i),
        .debug_req_i   (debug_req_i),
        .rvfi_probes_o (gold_rvfi_probes_o),
        .cvxif_req_o   (gold_cvxif_req_o),
        .cvxif_resp_i  (cvxif_resp_i),
        .noc_req_o     (gold_noc_req_o),
        .noc_resp_i    (noc_resp_i)
        `include "internal_helper_ports_a.vh"
    );

    gate_top i_gate (
        .clk_i         (clk_i),
        .rst_ni        (rst_ni),
        .boot_addr_i   (boot_addr_i),
        .hart_id_i     (hart_id_i),
        .irq_i         (irq_i),
        .ipi_i         (ipi_i),
        .time_irq_i    (time_irq_i),
        .debug_req_i   (debug_req_i),
        .rvfi_probes_o (gate_rvfi_probes_o),
        .cvxif_req_o   (gate_cvxif_req_o),
        .cvxif_resp_i  (cvxif_resp_i),
        .noc_req_o     (gate_noc_req_o),
        .noc_resp_i    (noc_resp_i)
        `include "internal_helper_ports_b.vh"
    );

    `ifdef FORMAL
    always_ff @(posedge clk_i) begin
            assert(gold_rvfi_probes_o == gate_rvfi_probes_o) else $error("RVFI Probes Mismatch");
            assert(gold_noc_req_o.aw_valid == gate_noc_req_o.aw_valid) else $error("NoC AW_VALID Mismatch");
            assert(gold_noc_req_o.w_valid  == gate_noc_req_o.w_valid)  else $error("NoC W_VALID Mismatch");
            assert(gold_noc_req_o.ar_valid == gate_noc_req_o.ar_valid) else $error("NoC AR_VALID Mismatch");
            
            assert(gold_noc_req_o.aw == gate_noc_req_o.aw) else $error("NoC AW Channel Mismatch");
            assert(gold_noc_req_o.w == gate_noc_req_o.w) else $error("NoC W Channel Mismatch");
            assert(gold_noc_req_o.ar == gate_noc_req_o.ar) else $error("NoC AR Channel Mismatch");

            assert(gold_cvxif_req_o == gate_cvxif_req_o) else $error("CVXIF Req Mismatch");
            `ifdef INTERNAL_ASSERTS
            `include "internal_helper_asserts.vh"
            `endif
    end
    `endif

endmodule
