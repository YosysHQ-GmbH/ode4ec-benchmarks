create_clock -name i_clk -period 10.0 [get_ports {i_clk}]

set_input_delay  -clock i_clk 1.0 [remove_from_collection [all_inputs] [get_ports {i_clk}]]
set_output_delay -clock i_clk 1.0 [all_outputs]
