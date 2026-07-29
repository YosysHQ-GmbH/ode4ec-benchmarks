yosys -import

plugin -i slang
read_slang --top picorv32 ../src/picorv32.v
hierarchy -top picorv32

memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename picorv32 gold_top
flatten
write_rtlil gold_out.il
