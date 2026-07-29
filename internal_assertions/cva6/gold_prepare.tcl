yosys -import

set design           $::env(TOP_MODULE)
set lib_file         $::env(TIMING_LIB)
set flist_vcs        $::env(FLIST)

# read design
plugin -i slang
read_slang -F ${flist_vcs} --top ${design}
hierarchy -top ${design}

memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename ${design} gold_top
flatten
write_rtlil gold_out.il
