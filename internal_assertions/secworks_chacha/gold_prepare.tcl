yosys -import

plugin -i slang
read_slang -keep-hierarchy --top chacha ../src/chacha.v ../src/chacha_core.v ../src/chacha_qr.v
hierarchy -top chacha

memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename chacha gold_top
flatten
write_rtlil gold_out.il
