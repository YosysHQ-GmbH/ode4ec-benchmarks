module miter (
    input busreq,
    input clk,
    input [31:0] dbusi,
    input [3:0] irq,
    input sreset
);
    wire [31:0] gold_abus;
    wire        gold_ads;
    wire [3:0]  gold_be;
    wire        gold_busack;
    wire [31:0] gold_dbuso;
    wire        gold_rd;
    wire        gold_wr;

    wire [31:0] gate_abus;
    wire        gate_ads;
    wire [3:0]  gate_be;
    wire        gate_busack;
    wire [31:0] gate_dbuso;
    wire        gate_rd;
    wire        gate_wr;

    `include "internal_helper_decls.vh"

    gold_top i_gold (
        .clk    (clk),
        .sreset (sreset),
        .busreq (busreq),
        .dbusi  (dbusi),
        .irq    (irq),

        .abus   (gold_abus),
        .ads    (gold_ads),
        .be     (gold_be),
        .busack (gold_busack),
        .dbuso  (gold_dbuso),
        .rd     (gold_rd),
        .wr     (gold_wr)
        `include "internal_helper_ports_a.vh"
    );

    gate_top i_gate (
        .clk    (clk),
        .sreset (sreset),
        .busreq (busreq),
        .dbusi  (dbusi),
        .irq    (irq),

        .abus   (gate_abus),
        .ads    (gate_ads),
        .be     (gate_be),
        .busack (gate_busack),
        .dbuso  (gate_dbuso),
        .rd     (gate_rd),
        .wr     (gate_wr)
        `include "internal_helper_ports_b.vh"
    );

    always @(posedge clk) begin
            assert(gold_abus   == gate_abus);
            assert(gold_ads    == gate_ads);
            assert(gold_be     == gate_be);
            assert(gold_busack == gate_busack);
            assert(gold_dbuso  == gate_dbuso);
            assert(gold_rd     == gate_rd);
            assert(gold_wr     == gate_wr);
            `ifdef INTERNAL_ASSERTS
            `include "internal_helper_asserts.vh"
            `endif
    end

endmodule
