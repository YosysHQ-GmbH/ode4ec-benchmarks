yosys -import

plugin -i slang
read_slang --top fftmain ../src/fftmain.v ../src/bimpy.v ../src/bitreverse.v ../src/butterfly.v ../src/convround.v ../src/fftstage.v ../src/hwbfly.v ../src/laststage.v ../src/longbimpy.v ../src/qtrstage.v
hierarchy -top fftmain

memory_map -formal
flatten
opt_clean -purge
chformal -assert -remove
yosys rename fftmain gold_top
flatten
write_rtlil gold_out.il
