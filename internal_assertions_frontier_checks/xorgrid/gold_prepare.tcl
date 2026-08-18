yosys -import

plugin -i slang
read_slang xorgrid.v --top xorgrid

hierarchy -check -top xorgrid
memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename xorgrid gold_top
flatten
write_rtlil gold.il
