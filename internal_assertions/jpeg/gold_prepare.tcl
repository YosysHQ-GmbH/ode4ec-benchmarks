yosys -import

plugin -i slang
read_slang --top jpeg_encoder --ignore-timing -I ../src/include ../src/*.v
hierarchy -top jpeg_encoder

memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename jpeg_encoder gold_top
flatten
write_rtlil gold_out.il
