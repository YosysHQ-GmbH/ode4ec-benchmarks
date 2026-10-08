# Based on yosys_synth.tcl
yosys -import

set design           $::env(TOP_MODULE)
set lib_file         $::env(TIMING_LIB)
set flist_vcs        $::env(FLIST)
set synth_v_file     $::env(WRAPPER_SYNTH)

# identify special cells/associated pins
# constants
set tiehi_cell       sky130_fd_sc_hd__conb_1
set tiehi_pin        HI
set tielo_cell       sky130_fd_sc_hd__conb_1
set tielo_pin        LO
# buffers
set clkbuf_cell      sky130_fd_sc_hd__clkbuf_1
set clkbuf_pin       X
set buf_cell         sky130_fd_sc_hd__buf_1
set buf_ipin         A
set buf_opin         X
# latches
set dlatch_p_cell    sky130_fd_sc_hd__dlxtp_1
set dlatch_p_d_pin   D
set dlatch_p_e_pin   GATE
set dlatch_p_q_pin   Q
set dlatch_n_cell    sky130_fd_sc_hd__dlxtn_1
set dlatch_n_d_pin   D
set dlatch_n_e_pin   GATE_N
set dlatch_n_q_pin   Q

# read design
plugin -i slang
read_slang -F ${flist_vcs} --top ${design}
hierarchy -top ${design}
# Remove formal properties (we really need to make synth do this by default)
chformal -remove

# run basic synthesis & logic optimization
synth -run :check
stat

# map to cell lib
dfflibmap -liberty ${lib_file}
dfflegalize -cell {$_DLATCH_?_} x
#techmap -map map_latch.v -D __DLATCH_P_CELL_TYPE=${dlatch_p_cell} -D __DLATCH_P_D_PIN=${dlatch_p_d_pin} -D __DLATCH_P_E_PIN=${dlatch_p_e_pin} -D __DLATCH_P_Q_PIN=${dlatch_p_q_pin}
abc -liberty ${lib_file}

# Split nets to single bits
splitnets
# Set X to zero
setundef -zero

# Clean up processing cruft
opt

# mapping constants and clock buffers to cell lib
hilomap -hicell ${tiehi_cell} ${tiehi_pin} -locell ${tielo_cell} ${tielo_pin}
clkbufmap -buf ${clkbuf_cell} ${clkbuf_pin}

# Insert buffers
insbuf -buf ${buf_cell} ${buf_ipin} ${buf_opin}

# Clean up the design
opt_clean -purge

flatten

# Check and print statistics
check -mapped -noinit
tee -o stat.txt stat -liberty ${lib_file}

# write synthesized design
yosys rename ${design} gate_top
flatten
write_rtlil ${synth_v_file}
