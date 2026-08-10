module registered_multi_macc #(
    parameter int A1_WIDTH = 4,
    parameter int B1_WIDTH = 8,
    parameter int A2_WIDTH = 4,
    parameter int B2_WIDTH = 8,
    parameter int C_WIDTH  = 2,
    parameter int D_WIDTH  = 16,
    parameter int Y_WIDTH  = 8
) (
    input  logic                clk,
    input  logic [A1_WIDTH-1:0] a1,
    input  logic [B1_WIDTH-1:0] b1,
    input  logic [A2_WIDTH-1:0] a2,
    input  logic [B2_WIDTH-1:0] b2,
    input  logic [C_WIDTH-1:0]  c,
    input  logic [D_WIDTH-1:0]  d,
    output logic [Y_WIDTH-1:0]  y
);
    logic [A1_WIDTH-1:0] a1_reg;
    logic [B1_WIDTH-1:0] b1_reg;
    logic [A2_WIDTH-1:0] a2_reg;
    logic [B2_WIDTH-1:0] b2_reg;
    logic [C_WIDTH-1:0]  c_reg;
    logic [D_WIDTH-1:0]  d_reg;
    logic [A1_WIDTH+B1_WIDTH-1:0] ab1;

    assign ab1 = a1_reg * b1_reg;

    always_ff @(posedge clk) begin
        a1_reg <= a1;
        b1_reg <= b1;
        a2_reg <= a2;
        b2_reg <= b2;
        c_reg  <= c;
        d_reg  <= d;

        y <= ab1 + a2_reg*b2_reg + c_reg + d_reg + 1;
    end
endmodule
