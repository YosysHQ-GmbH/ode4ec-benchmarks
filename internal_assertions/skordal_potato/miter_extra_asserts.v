// Verilog top-level miter used ONLY for the custom_miter_with_extra_asserts*
// sby variants.
//
// skordal_potato's design-level top (pp_potato) has a VHDL record-typed port
// (test_context_out : test_context), so the primary miter (miter.vhd) stays
// VHDL and is elaborated via ghdl, relying on the ghdl-yosys-plugin to
// deterministically lower that record into the same two split ports
// (\test_context_out[state], \test_context_out[number]) on both the
// component instantiation inside miter.vhd and the actual gold_top/gate_top
// RTLIL modules produced by gold_prepare.tcl/synth.tcl -- yosys `hierarchy`
// then binds them by name.
//
// generate_internal_asserts.py is a design-agnostic, byte-identical-across-
// projects script that always emits Verilog syntax (wire decls, named port
// connections, assert statements) meant to be `include`d into a Verilog
// module. VHDL has no `include`/`ifdef` preprocessor, so rather than hand-
// translating the generator's output into VHDL, this dedicated Verilog
// top-level is used only for the extra-asserts sby variants: it re-declares
// the same top-level I/O equivalence checks as miter.vhd (translated once,
// by hand) plus the generated internal register-equivalence checks. The
// plain custom_miter.sby/_mutation_check.sby variants keep using miter.vhd
// unchanged. The split test_context_out ports are connected here via
// Verilog escaped identifiers, matching the exact RTLIL port names.
module miter (
    input        clk,
    input        reset,
    input  [7:0] irq,
    input [31:0] wb_dat_in,
    input        wb_ack_in
);
    wire [1:0]  gold_test_context_state;
    wire [29:0] gold_test_context_number;
    wire [31:0] gold_wb_adr;
    wire [3:0]  gold_wb_sel;
    wire        gold_wb_cyc;
    wire        gold_wb_stb;
    wire        gold_wb_we;
    wire [31:0] gold_wb_dat_out;

    wire [1:0]  gate_test_context_state;
    wire [29:0] gate_test_context_number;
    wire [31:0] gate_wb_adr;
    wire [3:0]  gate_wb_sel;
    wire        gate_wb_cyc;
    wire        gate_wb_stb;
    wire        gate_wb_we;
    wire [31:0] gate_wb_dat_out;

    `include "internal_helper_decls.vh"

    gold_top i_gold (
        .clk    (clk),
        .reset  (reset),
        .irq    (irq),
        .wb_dat_in (wb_dat_in),
        .wb_ack_in (wb_ack_in),

        .\test_context_out[state]  (gold_test_context_state),
        .\test_context_out[number] (gold_test_context_number),
        .wb_adr_out (gold_wb_adr),
        .wb_sel_out (gold_wb_sel),
        .wb_cyc_out (gold_wb_cyc),
        .wb_stb_out (gold_wb_stb),
        .wb_we_out  (gold_wb_we),
        .wb_dat_out (gold_wb_dat_out)
        `include "internal_helper_ports_a.vh"
    );

    gate_top i_gate (
        .clk    (clk),
        .reset  (reset),
        .irq    (irq),
        .wb_dat_in (wb_dat_in),
        .wb_ack_in (wb_ack_in),

        .\test_context_out[state]  (gate_test_context_state),
        .\test_context_out[number] (gate_test_context_number),
        .wb_adr_out (gate_wb_adr),
        .wb_sel_out (gate_wb_sel),
        .wb_cyc_out (gate_wb_cyc),
        .wb_stb_out (gate_wb_stb),
        .wb_we_out  (gate_wb_we),
        .wb_dat_out (gate_wb_dat_out)
        `include "internal_helper_ports_b.vh"
    );

    always @(posedge clk) begin
            assert(gold_test_context_state  == gate_test_context_state);
            assert(gold_test_context_number == gate_test_context_number);
            assert(gold_wb_adr     == gate_wb_adr);
            assert(gold_wb_sel     == gate_wb_sel);
            assert(gold_wb_cyc     == gate_wb_cyc);
            assert(gold_wb_stb     == gate_wb_stb);
            assert(gold_wb_we      == gate_wb_we);
            assert(gold_wb_dat_out == gate_wb_dat_out);
            `ifdef INTERNAL_ASSERTS
            `include "internal_helper_asserts.vh"
            `endif
    end

endmodule
