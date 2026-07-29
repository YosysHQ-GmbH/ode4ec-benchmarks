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

ghdl --std=08 {*}$clean_files -e ${design}

hierarchy -top ${design}
memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename ${design} gold_top

# Project-specific: pin down don't-care post-stall-buffer registers in the
# pipeline so they don't cause spurious mismatches (preserved from the
# pre-conversion custom_miter.sby).
select -module gold_top
fminit -set processor.dmem_read_req_p 0
fminit -set processor.dmem_write_req_p 0
fminit -set processor.dmem_address_p 0
fminit -set processor.dmem_data_size_p 0
fminit -set processor.dmem_data_out_p 0
select -clear

flatten
write_rtlil gold_out.il
