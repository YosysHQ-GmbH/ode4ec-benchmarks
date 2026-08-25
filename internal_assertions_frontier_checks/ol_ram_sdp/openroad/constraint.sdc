create_clock -name Clk -period 10.0 [get_ports {Clk}]

set_input_delay  -clock Clk 1.0 [remove_from_collection [all_inputs] [get_ports {Clk}]]
set_output_delay -clock Clk 1.0 [all_outputs]
