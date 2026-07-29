yosys -import

set design           $::env(TOP_MODULE)
set lib_file         $::env(TIMING_LIB)
set flist_vcs        $::env(FLIST)

plugin -i ghdl
set fp [open ${flist_vcs} r]
set file_data [read ${fp}]
close $fp

set file_data [string map {"\r" ""} $file_data]

set clean_files {}
foreach f [split $file_data "\n"] {
    set clean_name [string trim $f]

    if {$clean_name ne ""} {
        lappend clean_files $clean_name
    }
}

ghdl --std=08 --work=neorv32 -gHART_ID=0 -gVENDOR_ID=00000000000000000000000000000000 -gBOOT_ADDR=00000000000000000000000000000000 -gDEBUG_PARK_ADDR=00000000000000000000000000000000 -gDEBUG_EXC_ADDR=00000000000000000000000000000000 -gCPU_TRACE_EN=true {*}$clean_files -e ${design}

hierarchy -top ${design}
memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename ${design} gold_top
flatten
write_rtlil gold_out.il
