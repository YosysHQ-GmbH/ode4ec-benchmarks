yosys -import

set design    $::env(TOP_MODULE)
set design_v  $::env(DESIGN_V)
set gold_out  $::env(GOLD_OUT)

# read design
plugin -i slang
read_slang ${design_v} --top ${design}

hierarchy -check -top ${design}
memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename ${design} gold_top
flatten
write_rtlil ${gold_out}
