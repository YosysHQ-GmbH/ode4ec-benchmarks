module registered_add_sub #(
    parameter int A_WIDTH = 4,
    parameter int B_WIDTH = 8,
    parameter int Y_WIDTH = 8
) (
    input  logic                    clk,
    input  logic [A_WIDTH-1:0]      a,
    input  logic [B_WIDTH-1:0]      b,
    input  logic                    subtract,
    output logic [Y_WIDTH-1:0] result
);
    logic [A_WIDTH-1:0] a_reg;
    logic [B_WIDTH-1:0] b_reg;
    logic               subtract_reg;

    always_ff @(posedge clk) begin
        a_reg        <= a;
        b_reg        <= b;
        subtract_reg <= subtract;

        if (subtract_reg) begin
            result <= a_reg - b_reg;
        end else begin
            result <= a_reg + b_reg;
        end
    end
endmodule
