module four_input_adder #(
    parameter int A_WIDTH = 4,
    parameter int B_WIDTH = 8,
    parameter int C_WIDTH = 2,
    parameter int D_WIDTH = 16,
    parameter int Y_WIDTH = 8
) (
    input  logic [A_WIDTH-1:0] a,
    input  logic [B_WIDTH-1:0] b,
    input  logic [C_WIDTH-1:0] c,
    input  logic [D_WIDTH-1:0] d,
    output logic [Y_WIDTH-1:0] y
);
    assign y = a + b + c + d;
endmodule
