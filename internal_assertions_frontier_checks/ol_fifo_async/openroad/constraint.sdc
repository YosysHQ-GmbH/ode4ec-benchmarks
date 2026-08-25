create_clock -name In_Clk  -period 10.0 [get_ports {In_Clk}]
create_clock -name Out_Clk -period 10.0 [get_ports {Out_Clk}]

set_clock_groups -asynchronous -group {In_Clk} -group {Out_Clk}

set_input_delay  -clock In_Clk 1.0 [get_ports {In_Rst In_Data In_Valid}]
set_input_delay  -clock Out_Clk 1.0 [get_ports {Out_Rst Out_Ready}]

set_output_delay -clock In_Clk 1.0 [get_ports {In_RstOut In_Ready In_Full In_Empty In_AlmFull In_AlmEmpty In_Level}]
set_output_delay -clock Out_Clk 1.0 [get_ports {Out_RstOut Out_Data Out_Valid Out_Full Out_Empty Out_AlmFull Out_AlmEmpty Out_Level}]
