yosys -import

plugin -i slang
read_slang -keep-hierarchy --top sha256 ../src/sha256.v ../src/sha256_core.v ../src/sha256_w_mem.v ../src/sha256_k_constants.v
hierarchy -top sha256

memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename sha256 gold_top
flatten
write_rtlil gold_out.il
