create_clock -name clock -period 10.0 [get_ports {clock}]

set_input_delay  -clock clock 1.0 [remove_from_collection [all_inputs] [get_ports {clock}]]
set_output_delay -clock clock 1.0 [all_outputs]
