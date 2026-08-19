yosys -import

set design        $::env(TOP_MODULE)
set instance_name $::env(DESIGN_INSTANCE_NAME)
set lib_file      $::env(TIMING_LIB)
set orfs_netlist  $::env(ORFS_NETLIST)
set synth_v_file  $::env(WRAPPER_SYNTH)

read_liberty -lib ${lib_file}
read_verilog ${orfs_netlist}
hierarchy -top ${instance_name}

flatten
opt_clean -purge

check -mapped -noinit
tee -o stat.txt stat -liberty ${lib_file}

yosys rename ${instance_name} gate_top
write_rtlil ${synth_v_file}
