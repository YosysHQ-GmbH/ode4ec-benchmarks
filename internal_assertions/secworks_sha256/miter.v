module miter (
    input wire        clk,
    input wire        reset_n,

    input wire        cs,
    input wire        we,
    input wire [7:0]  address,
    input wire [31:0] write_data
);

    wire [31:0] gold_read_data;
    wire [31:0] gate_read_data;
    wire        gold_error;
    wire        gate_error;

    `include "internal_helper_decls.vh"

    gold_top i_gold (
        .clk        (clk),
        .reset_n    (reset_n),
        .cs         (cs),
        .we         (we),
        .address    (address),
        .write_data (write_data),
        .read_data  (gold_read_data),
        .error      (gold_error)
        `include "internal_helper_ports_a.vh"
    );

    gate_top i_gate (
        .clk        (clk),
        .reset_n    (reset_n),
        .cs         (cs),
        .we         (we),
        .address    (address),
        .write_data (write_data),
        .read_data  (gate_read_data),
        .error      (gate_error)
        `include "internal_helper_ports_b.vh"
    );

    always @(posedge clk) begin
        assert(gold_read_data == gate_read_data);
        assert(gold_error == gate_error);
`ifdef INTERNAL_ASSERTS
        `include "internal_helper_asserts.vh"
`endif
    end

endmodule
