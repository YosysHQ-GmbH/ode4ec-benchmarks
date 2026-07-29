yosys -import

set gate_in    $::env(GATE_IN)
set mutated_out $::env(MUTATED_OUT)

read_rtlil ${gate_in}
yosys cd gate_top

select -set mutants \
    t:sky130_fd_sc_hd__and2_1 t:sky130_fd_sc_hd__or2_1 %u t:sky130_fd_sc_hd__xor2_1 %u \
    t:sky130_fd_sc_hd__nand2_1 %u t:sky130_fd_sc_hd__nor2_1 %u t:sky130_fd_sc_hd__xnor2_1 %u \
    %R100

select -set mutants_and  @mutants t:sky130_fd_sc_hd__and2_1  %i
select -set mutants_or   @mutants t:sky130_fd_sc_hd__or2_1   %i
select -set mutants_xor  @mutants t:sky130_fd_sc_hd__xor2_1  %i
select -set mutants_nand @mutants t:sky130_fd_sc_hd__nand2_1 %i
select -set mutants_nor  @mutants t:sky130_fd_sc_hd__nor2_1  %i
select -set mutants_xnor @mutants t:sky130_fd_sc_hd__xnor2_1 %i

chtype -map \sky130_fd_sc_hd__and2_1  \sky130_fd_sc_hd__or2_1   @mutants_and
chtype -map \sky130_fd_sc_hd__or2_1   \sky130_fd_sc_hd__xor2_1  @mutants_or
chtype -map \sky130_fd_sc_hd__xor2_1  \sky130_fd_sc_hd__and2_1  @mutants_xor
chtype -map \sky130_fd_sc_hd__nand2_1 \sky130_fd_sc_hd__nor2_1  @mutants_nand
chtype -map \sky130_fd_sc_hd__nor2_1  \sky130_fd_sc_hd__xnor2_1 @mutants_nor
chtype -map \sky130_fd_sc_hd__xnor2_1 \sky130_fd_sc_hd__nand2_1 @mutants_xnor

select -clear
yosys cd ..

write_rtlil ${mutated_out}
