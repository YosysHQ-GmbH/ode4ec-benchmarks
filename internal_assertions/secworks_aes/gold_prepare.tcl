yosys -import

plugin -i slang
read_slang -keep-hierarchy --top aes ../src/aes.v ../src/aes_core.v ../src/aes_decipher_block.v ../src/aes_encipher_block.v ../src/aes_inv_sbox.v ../src/aes_key_mem.v ../src/aes_sbox.v
hierarchy -top aes

memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename aes gold_top
flatten
write_rtlil gold_out.il
