yosys -import

# read design
plugin -i slang
read_slang -F ../../files.txt --top corescore_de10_nano --allow-use-before-declare

hierarchy -check -top corescore_de10_nano
memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename corescore_de10_nano gold_top
flatten
write_rtlil gold.il
