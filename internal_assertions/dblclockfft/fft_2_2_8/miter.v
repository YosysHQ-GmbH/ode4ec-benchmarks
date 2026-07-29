module miter (
    input i_clk,
    input i_reset,
    input i_ce,
    input [15:0] i_sample
);

    wire gold_o_sync, gate_o_sync;
    wire [17:0] gold_o_result, gate_o_result;

    `include "internal_helper_decls.vh"

    gold_top i_gold (
        .i_clk(i_clk),
        .i_reset(i_reset),
        .i_ce(i_ce),
        .i_sample(i_sample),
        .o_result(gold_o_result),
        .o_sync(gold_o_sync)
        `include "internal_helper_ports_a.vh"
    );

    gate_top i_gate (
        .i_clk(i_clk),
        .i_reset(i_reset),
        .i_ce(i_ce),
        .i_sample(i_sample),
        .o_result(gate_o_result),
        .o_sync(gate_o_sync)
        `include "internal_helper_ports_b.vh"
    );

    always @(posedge i_clk) begin
        assert(gold_o_sync == gate_o_sync);
        assert(gold_o_result == gate_o_result);
`ifdef INTERNAL_ASSERTS
        `include "internal_helper_asserts.vh"
`endif
    end
endmodule
