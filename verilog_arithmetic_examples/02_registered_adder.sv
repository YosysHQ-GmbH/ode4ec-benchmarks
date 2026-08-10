module registered_adder #(
    parameter int A_WIDTH = 4,
    parameter int B_WIDTH = 8,
    parameter int Y_WIDTH = 8
) (
    input  logic                    clk,
    input  logic [A_WIDTH-1:0]      a,
    input  logic [B_WIDTH-1:0]      b,
    output logic [Y_WIDTH-1:0] result
);
    always_ff @(posedge clk) begin
        result <= a + b;
    end
endmodule
