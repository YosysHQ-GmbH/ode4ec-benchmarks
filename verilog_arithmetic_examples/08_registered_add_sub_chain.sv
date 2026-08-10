module registered_add_sub_chain #(
    parameter int A_WIDTH = 4,
    parameter int B_WIDTH = 8,
    parameter int C_WIDTH = 16,
    parameter int D_WIDTH = 2,
    parameter int Y_WIDTH = 8
) (
    input  logic               clk,
    input  logic [A_WIDTH-1:0] a,
    input  logic [B_WIDTH-1:0] b,
    input  logic [C_WIDTH-1:0] c,
    input  logic [D_WIDTH-1:0] d,
    output logic [Y_WIDTH-1:0] y
);
    logic [A_WIDTH-1:0] a_reg;
    logic [B_WIDTH-1:0] b_reg;
    logic [C_WIDTH-1:0] c_reg;
    logic [D_WIDTH-1:0] d_reg;

    always_ff @(posedge clk) begin
        a_reg <= a;
        b_reg <= b;
        c_reg <= c;
        d_reg <= d;

        y <= a_reg + b_reg + c_reg - d_reg;
    end
endmodule
