module miter (
    input clk_i,
    input rstn_i,
    input [31:0] ibus_data_in,
    input [31:0] dbus_data_in,
    input [63:0] mtime_i,
    input msi_i,
    input mei_i,
    input mti_i,
    input [15:0] firq_i,
    input dbi_i,
    input ibus_err_i,
    input dbus_err_i
);

    wire gold_sleep_o, gate_sleep_o;
    wire [1:0] gold_fence_o, gate_fence_o;

    wire [31:0] gold_ibus_addr, gate_ibus_addr;
    wire [31:0] gold_ibus_data, gate_ibus_data;
    wire gold_ibus_stb, gate_ibus_stb;
    wire gold_ibus_rw, gate_ibus_rw;

    wire [31:0] gold_dbus_addr, gate_dbus_addr;
    wire [31:0] gold_dbus_data, gate_dbus_data;
    wire gold_dbus_stb, gate_dbus_stb;
    wire gold_dbus_rw, gate_dbus_rw;

    wire gold_trace_valid, gate_trace_valid;
    wire [31:0] gold_trace_order, gate_trace_order;
    wire [31:0] gold_trace_insn, gate_trace_insn;
    wire gold_trace_trap, gate_trace_trap;
    wire gold_trace_halt, gate_trace_halt;
    wire gold_trace_intr, gate_trace_intr;
    wire [1:0] gold_trace_mode, gate_trace_mode;
    wire [1:0] gold_trace_ixl, gate_trace_ixl;
    wire gold_trace_debug, gate_trace_debug;
    wire gold_trace_compr, gate_trace_compr;
    wire gold_trace_delta, gate_trace_delta;
    wire [31:0] gold_trace_cmd32, gate_trace_cmd32;
    wire [4:0] gold_trace_rs1_addr, gate_trace_rs1_addr;
    wire [4:0] gold_trace_rs2_addr, gate_trace_rs2_addr;
    wire [31:0] gold_trace_rs1_rdata, gate_trace_rs1_rdata;
    wire [31:0] gold_trace_rs2_rdata, gate_trace_rs2_rdata;
    wire [4:0] gold_trace_rd_addr, gate_trace_rd_addr;
    wire [31:0] gold_trace_rd_rdata, gate_trace_rd_rdata;
    wire [31:0] gold_trace_pc_rdata, gate_trace_pc_rdata;
    wire [31:0] gold_trace_pc_wdata, gate_trace_pc_wdata;
    wire [11:0] gold_trace_csr_addr, gate_trace_csr_addr;
    wire [31:0] gold_trace_csr_rdata, gate_trace_csr_rdata;
    wire [31:0] gold_trace_csr_wdata, gate_trace_csr_wdata;
    wire [31:0] gold_trace_mem_addr, gate_trace_mem_addr;
    wire [3:0] gold_trace_mem_rmask, gate_trace_mem_rmask;
    wire [3:0] gold_trace_mem_wmask, gate_trace_mem_wmask;
    wire [31:0] gold_trace_mem_rdata, gate_trace_mem_rdata;
    wire [31:0] gold_trace_mem_wdata, gate_trace_mem_wdata;

    `include "internal_helper_decls.vh"

    gold_top i_gold (
        .clk_i(clk_i),
        .rstn_i(rstn_i),
        .mtime_i(mtime_i),
        .msi_i(msi_i), .mei_i(mei_i), .mti_i(mti_i), .firq_i(firq_i), .dbi_i(dbi_i),

        .\ibus_rsp_i[ack]  (gold_ibus_stb),
        .\ibus_rsp_i[err]  (ibus_err_i),
        .\ibus_rsp_i[data] (ibus_data_in),

        .\dbus_rsp_i[ack]  (gold_dbus_stb),
        .\dbus_rsp_i[err]  (dbus_err_i),
        .\dbus_rsp_i[data] (dbus_data_in),

        .sleep_o(gold_sleep_o),
        .fence_o(gold_fence_o),

        .\ibus_req_o[addr] (gold_ibus_addr),
        .\ibus_req_o[data] (gold_ibus_data),
        .\ibus_req_o[stb]  (gold_ibus_stb),
        .\ibus_req_o[rw]   (gold_ibus_rw),

        .\dbus_req_o[addr] (gold_dbus_addr),
        .\dbus_req_o[data] (gold_dbus_data),
        .\dbus_req_o[stb]  (gold_dbus_stb),
        .\dbus_req_o[rw]   (gold_dbus_rw),

        .\trace_o[valid]     (gold_trace_valid),
        .\trace_o[order]     (gold_trace_order),
        .\trace_o[insn]      (gold_trace_insn),
        .\trace_o[trap]      (gold_trace_trap),
        .\trace_o[halt]      (gold_trace_halt),
        .\trace_o[intr]      (gold_trace_intr),
        .\trace_o[mode]      (gold_trace_mode),
        .\trace_o[ixl]       (gold_trace_ixl),
        .\trace_o[debug]     (gold_trace_debug),
        .\trace_o[compr]     (gold_trace_compr),
        .\trace_o[delta]     (gold_trace_delta),
        .\trace_o[cmd32]     (gold_trace_cmd32),
        .\trace_o[rs1_addr]  (gold_trace_rs1_addr),
        .\trace_o[rs2_addr]  (gold_trace_rs2_addr),
        .\trace_o[rs1_rdata] (gold_trace_rs1_rdata),
        .\trace_o[rs2_rdata] (gold_trace_rs2_rdata),
        .\trace_o[rd_addr]   (gold_trace_rd_addr),
        .\trace_o[rd_rdata]  (gold_trace_rd_rdata),
        .\trace_o[pc_rdata]  (gold_trace_pc_rdata),
        .\trace_o[pc_wdata]  (gold_trace_pc_wdata),
        .\trace_o[csr_addr]  (gold_trace_csr_addr),
        .\trace_o[csr_rdata] (gold_trace_csr_rdata),
        .\trace_o[csr_wdata] (gold_trace_csr_wdata),
        .\trace_o[mem_addr]  (gold_trace_mem_addr),
        .\trace_o[mem_rmask] (gold_trace_mem_rmask),
        .\trace_o[mem_wmask] (gold_trace_mem_wmask),
        .\trace_o[mem_rdata] (gold_trace_mem_rdata),
        .\trace_o[mem_wdata] (gold_trace_mem_wdata)
`ifdef INTERNAL_ASSERTS
        `include "internal_helper_ports_a.vh"
`endif
    );

    gate_top i_gate (
        .clk_i(clk_i),
        .rstn_i(rstn_i),
        .mtime_i(mtime_i),
        .msi_i(msi_i), .mei_i(mei_i), .mti_i(mti_i), .firq_i(firq_i), .dbi_i(dbi_i),

        .\ibus_rsp_i[ack]  (gate_ibus_stb),
        .\ibus_rsp_i[err]  (ibus_err_i),
        .\ibus_rsp_i[data] (ibus_data_in),

        .\dbus_rsp_i[ack]  (gate_dbus_stb),
        .\dbus_rsp_i[err]  (dbus_err_i),
        .\dbus_rsp_i[data] (dbus_data_in),

        .sleep_o(gate_sleep_o),
        .fence_o(gate_fence_o),

        .\ibus_req_o[addr] (gate_ibus_addr),
        .\ibus_req_o[data] (gate_ibus_data),
        .\ibus_req_o[stb]  (gate_ibus_stb),
        .\ibus_req_o[rw]   (gate_ibus_rw),

        .\dbus_req_o[addr] (gate_dbus_addr),
        .\dbus_req_o[data] (gate_dbus_data),
        .\dbus_req_o[stb]  (gate_dbus_stb),
        .\dbus_req_o[rw]   (gate_dbus_rw),

        .\trace_o[valid]     (gate_trace_valid),
        .\trace_o[order]     (gate_trace_order),
        .\trace_o[insn]      (gate_trace_insn),
        .\trace_o[trap]      (gate_trace_trap),
        .\trace_o[halt]      (gate_trace_halt),
        .\trace_o[intr]      (gate_trace_intr),
        .\trace_o[mode]      (gate_trace_mode),
        .\trace_o[ixl]       (gate_trace_ixl),
        .\trace_o[debug]     (gate_trace_debug),
        .\trace_o[compr]     (gate_trace_compr),
        .\trace_o[delta]     (gate_trace_delta),
        .\trace_o[cmd32]     (gate_trace_cmd32),
        .\trace_o[rs1_addr]  (gate_trace_rs1_addr),
        .\trace_o[rs2_addr]  (gate_trace_rs2_addr),
        .\trace_o[rs1_rdata] (gate_trace_rs1_rdata),
        .\trace_o[rs2_rdata] (gate_trace_rs2_rdata),
        .\trace_o[rd_addr]   (gate_trace_rd_addr),
        .\trace_o[rd_rdata]  (gate_trace_rd_rdata),
        .\trace_o[pc_rdata]  (gate_trace_pc_rdata),
        .\trace_o[pc_wdata]  (gate_trace_pc_wdata),
        .\trace_o[csr_addr]  (gate_trace_csr_addr),
        .\trace_o[csr_rdata] (gate_trace_csr_rdata),
        .\trace_o[csr_wdata] (gate_trace_csr_wdata),
        .\trace_o[mem_addr]  (gate_trace_mem_addr),
        .\trace_o[mem_rmask] (gate_trace_mem_rmask),
        .\trace_o[mem_wmask] (gate_trace_mem_wmask),
        .\trace_o[mem_rdata] (gate_trace_mem_rdata),
        .\trace_o[mem_wdata] (gate_trace_mem_wdata)
`ifdef INTERNAL_ASSERTS
        `include "internal_helper_ports_b.vh"
`endif
    );

    always @(posedge clk_i) begin
        assert(gold_sleep_o == gate_sleep_o);
        assert(gold_fence_o == gate_fence_o);

        assert(gold_ibus_addr == gate_ibus_addr);
        assert(gold_ibus_data == gate_ibus_data);
        assert(gold_ibus_stb  == gate_ibus_stb);
        assert(gold_ibus_rw   == gate_ibus_rw);

        assert(gold_dbus_addr == gate_dbus_addr);
        assert(gold_dbus_data == gate_dbus_data);
        assert(gold_dbus_stb  == gate_dbus_stb);
        assert(gold_dbus_rw   == gate_dbus_rw);

        assert(gold_trace_valid     == gate_trace_valid);
        assert(gold_trace_order     == gate_trace_order);
        assert(gold_trace_insn      == gate_trace_insn);
        assert(gold_trace_trap      == gate_trace_trap);
        assert(gold_trace_halt      == gate_trace_halt);
        assert(gold_trace_intr      == gate_trace_intr);
        assert(gold_trace_mode      == gate_trace_mode);
        assert(gold_trace_ixl       == gate_trace_ixl);
        assert(gold_trace_debug     == gate_trace_debug);
        assert(gold_trace_compr     == gate_trace_compr);
        assert(gold_trace_delta     == gate_trace_delta);
        assert(gold_trace_cmd32     == gate_trace_cmd32);
        assert(gold_trace_rs1_addr  == gate_trace_rs1_addr);
        assert(gold_trace_rs2_addr  == gate_trace_rs2_addr);
        assert(gold_trace_rs1_rdata == gate_trace_rs1_rdata);
        assert(gold_trace_rs2_rdata == gate_trace_rs2_rdata);
        assert(gold_trace_rd_addr   == gate_trace_rd_addr);
        assert(gold_trace_rd_rdata  == gate_trace_rd_rdata);
        assert(gold_trace_pc_rdata  == gate_trace_pc_rdata);
        assert(gold_trace_pc_wdata  == gate_trace_pc_wdata);
        assert(gold_trace_csr_addr  == gate_trace_csr_addr);
        assert(gold_trace_csr_rdata == gate_trace_csr_rdata);
        assert(gold_trace_csr_wdata == gate_trace_csr_wdata);
        assert(gold_trace_mem_addr  == gate_trace_mem_addr);
        assert(gold_trace_mem_rmask == gate_trace_mem_rmask);
        assert(gold_trace_mem_wmask == gate_trace_mem_wmask);
        assert(gold_trace_mem_rdata == gate_trace_mem_rdata);
        assert(gold_trace_mem_wdata == gate_trace_mem_wdata);
        `ifdef INTERNAL_ASSERTS
        `include "internal_helper_asserts.vh"
        `endif
    end
endmodule
