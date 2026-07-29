yosys -import

plugin -i slang
read_slang -keep-hierarchy --top poly1305 ../src/poly1305.v ../src/poly1305_core.v ../src/poly1305_final.v ../src/poly1305_mulacc.v ../src/poly1305_pblock.v
hierarchy -top poly1305

memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename poly1305 gold_top
flatten
write_rtlil gold_out.il
