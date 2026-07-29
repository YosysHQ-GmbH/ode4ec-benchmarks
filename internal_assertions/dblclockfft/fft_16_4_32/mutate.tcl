yosys -import

read_liberty -ignore_miss_func ../sky130/sky130_fd_sc_hd__tt_025C_1v80.lib
read_rtlil gate_out.il
yosys cd gate_top

mutate -list 10 -seed $::env(SEED) -o mutations.txt

set fp [open "mutations.txt" r]
set mutation_lines [split [string trim [read $fp]] "\n"]
close $fp
foreach mutation_line $mutation_lines {
    set mutation_words [regexp -all -inline {\S+} $mutation_line]
    {*}$mutation_words
}

yosys cd ..

select gate_top
setattr -unset init
write_rtlil -selected gate_out_mutated.il
select -clear
