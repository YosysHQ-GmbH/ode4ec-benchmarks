DEPTHS ?= 4 16 32 64 128
WIDTHS ?= 8 16 32 64

export TIMING_LIB=../sky130/sky130_fd_sc_hd__tt_025C_1v80.lib
export FLIST=../files.txt
export TOP_MODULE=olo_base_ram_sp

ORFS_HOME ?= $(abspath ../orfs)
export PLATFORM = sky130hd

COMBOS := $(shell \
    for w in $(WIDTHS); do \
        for d in $(DEPTHS); do \
            printf "W$${w}_D$${d} "; \
        done; \
    done \
)

FLAVORS := yosys orfs

YOSYS_NETLISTS := $(foreach c,$(COMBOS),run/check_$(c)_yosys_netlist.v)
ORFS_NETLISTS  := $(foreach c,$(COMBOS),run/check_$(c)_orfs_netlist.v)

EQY_TARGETS            := $(foreach c,$(COMBOS),$(foreach f,$(FLAVORS),eqy_$(c)_$(f)))
SBY_TARGETS             := $(foreach c,$(COMBOS),$(foreach f,$(FLAVORS),sby_$(c)_$(f)))
CUSTOM_MITER_TARGETS    := $(foreach c,$(COMBOS),$(foreach f,$(FLAVORS),custom-miter_$(c)_$(f)))
MUTATION_CHECK_TARGETS  := $(foreach c,$(COMBOS),$(foreach f,$(FLAVORS),mutation-check_$(c)_$(f)))
CUSTOM_MITER_EXTRA_ASSERTS_TARGETS   := $(foreach c,$(COMBOS),$(foreach f,$(FLAVORS),custom-miter-extra-asserts_$(c)_$(f)))
MUTATION_CHECK_EXTRA_ASSERTS_TARGETS := $(foreach c,$(COMBOS),$(foreach f,$(FLAVORS),mutation-check-extra-asserts_$(c)_$(f)))

.PHONY: all clean synth eqy sby openroad-synth custom-miter mutation-check \
	custom-miter-extra-asserts mutation-check-extra-asserts \
	eqy-orfs sby-orfs custom-miter-orfs mutation-check-orfs \
	custom-miter-extra-asserts-orfs mutation-check-extra-asserts-orfs \
	$(EQY_TARGETS) $(SBY_TARGETS) $(CUSTOM_MITER_TARGETS) $(MUTATION_CHECK_TARGETS) \
	$(CUSTOM_MITER_EXTRA_ASSERTS_TARGETS) $(MUTATION_CHECK_EXTRA_ASSERTS_TARGETS)

all: synth eqy sby

synth: $(YOSYS_NETLISTS)
openroad-synth: $(ORFS_NETLISTS)

eqy:           $(foreach c,$(COMBOS),eqy_$(c)_yosys)
sby:           $(foreach c,$(COMBOS),sby_$(c)_yosys)
custom-miter:  $(foreach c,$(COMBOS),custom-miter_$(c)_yosys)
mutation-check: $(foreach c,$(COMBOS),mutation-check_$(c)_yosys)
custom-miter-extra-asserts:  $(foreach c,$(COMBOS),custom-miter-extra-asserts_$(c)_yosys)
mutation-check-extra-asserts: $(foreach c,$(COMBOS),mutation-check-extra-asserts_$(c)_yosys)

eqy-orfs:            $(foreach c,$(COMBOS),eqy_$(c)_orfs)
sby-orfs:            $(foreach c,$(COMBOS),sby_$(c)_orfs)
custom-miter-orfs:   $(foreach c,$(COMBOS),custom-miter_$(c)_orfs)
mutation-check-orfs: $(foreach c,$(COMBOS),mutation-check_$(c)_orfs)
custom-miter-extra-asserts-orfs:   $(foreach c,$(COMBOS),custom-miter-extra-asserts_$(c)_orfs)
mutation-check-extra-asserts-orfs: $(foreach c,$(COMBOS),mutation-check-extra-asserts_$(c)_orfs)

run/check_%_yosys_netlist.v: synth.tcl.in
	@mkdir -p run
	@WIDTH=$$(echo $* | cut -d'_' -f1 | tr -d 'W'); \
	DEPTH=$$(echo $* | cut -d'_' -f2 | tr -d 'D'); \
	run_name="check_W$${WIDTH}_D$${DEPTH}_yosys"; \
	synth_file="$${run_name}_synth.tcl"; \
	sed -e "s/@WIDTH@/$$WIDTH/g" -e "s/@DEPTH@/$$DEPTH/g" -e "s/@NETLIST@/$${run_name}_netlist.v/g" synth.tcl.in > run/$$synth_file; \
	export WIDTH=$$WIDTH; \
	export DEPTH=$$DEPTH; \
	export WRAPPER_SYNTH=$${run_name}_netlist.v; \
	cd run && yosys -m ghdl -c $$synth_file

run/check_%_gold.il: gold_prepare.tcl.in
	@mkdir -p run
	@WIDTH=$$(echo $* | cut -d'_' -f1 | tr -d 'W'); \
	DEPTH=$$(echo $* | cut -d'_' -f2 | tr -d 'D'); \
	run_name="check_W$${WIDTH}_D$${DEPTH}"; \
	prep_file="$${run_name}_gold_prepare.tcl"; \
	sed -e "s/@WIDTH@/$$WIDTH/g" -e "s/@DEPTH@/$$DEPTH/g" -e "s/@GOLD@/$${run_name}_gold.il/g" gold_prepare.tcl.in > run/$$prep_file; \
	export WIDTH=$$WIDTH; \
	export DEPTH=$$DEPTH; \
	cd run && yosys -m ghdl -c $$prep_file

run/check_%_gate.il: run/check_%_netlist.v gate_prepare.tcl.in
	@WIDTH=$$(echo $* | cut -d'_' -f1 | tr -d 'W'); \
	DEPTH=$$(echo $* | cut -d'_' -f2 | tr -d 'D'); \
	FLAVOR=$$(echo $* | cut -d'_' -f3); \
	run_name="check_W$${WIDTH}_D$${DEPTH}_$${FLAVOR}"; \
	netlist="$${run_name}_netlist.v"; \
	prep_file="$${run_name}_gate_prepare.tcl"; \
	sed -e "s/@NETLIST@/$$netlist/g" -e "s/@GATE@/$${run_name}_gate.il/g" gate_prepare.tcl.in > run/$$prep_file; \
	cd run && yosys -m slang -c $$prep_file

run/check_%_orfs_netlist.v: openroad/pre_synth.tcl openroad/post_synth.tcl openroad/config.mk.in openroad/constraint.sdc
	@if [ ! -d "$(ORFS_HOME)/flow" ]; then \
		echo "No OpenROAD-flow-scripts checkout at $(ORFS_HOME). Run 'make orfs' from $(abspath ..) to fetch it, or pass ORFS_HOME=/path/to/OpenROAD-flow-scripts."; \
		exit 1; \
	fi
	@mkdir -p openroad/run run
	@WIDTH=$$(echo $* | cut -d'_' -f1 | tr -d 'W'); \
	DEPTH=$$(echo $* | cut -d'_' -f2 | tr -d 'D'); \
	run_name="check_W$${WIDTH}_D$${DEPTH}_orfs"; \
	flat_v="$(CURDIR)/openroad/run/$${run_name}_flat.v"; \
	config_mk="$(CURDIR)/openroad/run/$${run_name}_config.mk"; \
	sed -e "s/@WIDTH@/$$WIDTH/g" -e "s/@DEPTH@/$$DEPTH/g" \
	    -e "s#@PRE_SYNTH_V@#$$flat_v#g" \
	    -e "s#@CONSTRAINT_SDC@#$(CURDIR)/openroad/constraint.sdc#g" \
	    openroad/config.mk.in > $$config_mk; \
	instance_name="olo_base_ram_sp_W$${WIDTH}_D$${DEPTH}"; \
	orfs_synth_target="results/sky130hd/$${instance_name}/base/1_2_yosys.v"; \
	( export WIDTH=$$WIDTH; export DEPTH=$$DEPTH; export PRE_SYNTH_V=$$flat_v; \
	  export DESIGN_INSTANCE_NAME=$$instance_name; \
	  cd openroad && yosys -m ghdl -c pre_synth.tcl ) && \
	$(MAKE) -C $(ORFS_HOME)/flow DESIGN_CONFIG=$$config_mk \
		YOSYS_EXE=$(shell command -v yosys) $$orfs_synth_target && \
	( export ORFS_NETLIST=$(ORFS_HOME)/flow/$$orfs_synth_target; \
	  export WRAPPER_SYNTH=$(CURDIR)/run/$${run_name}_netlist.v; \
	  export DESIGN_INSTANCE_NAME=$$instance_name; \
	  cd openroad && yosys -c post_synth.tcl )

$(EQY_TARGETS): eqy_%: run/check_%_netlist.v check.eqy.in
	@WIDTH=$$(echo $* | cut -d'_' -f1 | tr -d 'W'); \
	DEPTH=$$(echo $* | cut -d'_' -f2 | tr -d 'D'); \
	FLAVOR=$$(echo $* | cut -d'_' -f3); \
	run_name="check_W$${WIDTH}_D$${DEPTH}_$${FLAVOR}"; \
	eqy_file="$${run_name}.eqy"; \
	sed -e "s/@WIDTH@/$$WIDTH/g" -e "s/@DEPTH@/$$DEPTH/g" -e "s/@NETLIST@/$${run_name}_netlist.v/g" check.eqy.in > run/$$eqy_file; \
	cd run && timeout 1m eqy -f -d $${run_name}_eqy $$eqy_file

$(SBY_TARGETS): sby_%: run/check_%_netlist.v check.sby.in
	@WIDTH=$$(echo $* | cut -d'_' -f1 | tr -d 'W'); \
	DEPTH=$$(echo $* | cut -d'_' -f2 | tr -d 'D'); \
	FLAVOR=$$(echo $* | cut -d'_' -f3); \
	run_name="check_W$${WIDTH}_D$${DEPTH}_$${FLAVOR}"; \
	sby_file="$${run_name}.sby"; \
	sed -e "s/@WIDTH@/$$WIDTH/g" -e "s/@DEPTH@/$$DEPTH/g" -e "s/@NETLIST@/$${run_name}_netlist.v/g" check.sby.in > run/$$sby_file; \
	cd run && sby -j 2 -f --prefix $${run_name}_sby $$sby_file

$(CUSTOM_MITER_TARGETS): custom-miter_%: run/check_%_netlist.v custom_miter.sby.in miter.v.in
	@WIDTH=$$(echo $* | cut -d'_' -f1 | tr -d 'W'); \
	DEPTH=$$(echo $* | cut -d'_' -f2 | tr -d 'D'); \
	FLAVOR=$$(echo $* | cut -d'_' -f3); \
	run_name="check_W$${WIDTH}_D$${DEPTH}_$${FLAVOR}"; \
	$(MAKE) run/check_W$${WIDTH}_D$${DEPTH}_gold.il run/$${run_name}_gate.il; \
	gold="check_W$${WIDTH}_D$${DEPTH}_gold.il"; \
	gate="$${run_name}_gate.il"; \
	miter_file="$${run_name}_miter.v"; \
	sby_file="$${run_name}_custom_miter.sby"; \
	sed -e "s/@WIDTH@/$$WIDTH/g" -e "s/@DEPTH@/$$DEPTH/g" miter.v.in > run/$$miter_file; \
	sed -e "s/@MITER@/$$miter_file/g" -e "s/@GOLD@/$$gold/g" -e "s/@GATE@/$$gate/g" custom_miter.sby.in > run/$$sby_file; \
	cd run && sby -j 2 -f --prefix $${run_name}_custom_miter $$sby_file

$(MUTATION_CHECK_TARGETS): mutation-check_%: run/check_%_netlist.v custom_miter_mutation_check.sby.in miter.v.in mutate.tcl.in
	@WIDTH=$$(echo $* | cut -d'_' -f1 | tr -d 'W'); \
	DEPTH=$$(echo $* | cut -d'_' -f2 | tr -d 'D'); \
	FLAVOR=$$(echo $* | cut -d'_' -f3); \
	run_name="check_W$${WIDTH}_D$${DEPTH}_$${FLAVOR}"; \
	$(MAKE) run/check_W$${WIDTH}_D$${DEPTH}_gold.il; \
	gold="check_W$${WIDTH}_D$${DEPTH}_gold.il"; \
	netlist="$${run_name}_netlist.v"; \
	mutated="$${run_name}_netlist_mutated.il"; \
	mutate_file="$${run_name}_mutate.tcl"; \
	miter_file="$${run_name}_miter.v"; \
	sby_file="$${run_name}_mutation_check.sby"; \
	SEED=$$(od -An -N4 -tu4 /dev/urandom | tr -d ' '); \
	sed -e "s/@NETLIST@/$$netlist/g" -e "s/@MUTATED@/$$mutated/g" -e "s/@SEED@/$$SEED/g" -e "s/@NMUTATIONS@/10/g" mutate.tcl.in > run/$$mutate_file; \
	sed -e "s/@WIDTH@/$$WIDTH/g" -e "s/@DEPTH@/$$DEPTH/g" miter.v.in > run/$$miter_file; \
	sed -e "s/@MUTATED@/$$mutated/g" -e "s/@MITER@/$$miter_file/g" -e "s/@GOLD@/$$gold/g" custom_miter_mutation_check.sby.in > run/$$sby_file; \
	cd run && yosys -m slang -c $$mutate_file && \
	rm -rf $${run_name}_mutation_check && \
	( sby -f --prefix $${run_name}_mutation_check $$sby_file; true ) && \
	status=$$(cut -d' ' -f1 $${run_name}_mutation_check/status) && \
	if [ "$$status" = "FAIL" ]; then \
		echo "mutation-check $*: PASSED (miter correctly caught the injected gate mutation)"; \
	else \
		echo "mutation-check $*: FAILED (expected FAIL, got '$$status' - the miter may not be checking anything!)"; \
		exit 1; \
	fi

$(CUSTOM_MITER_EXTRA_ASSERTS_TARGETS): custom-miter-extra-asserts_%: run/check_%_netlist.v custom_miter_with_extra_asserts.sby.in miter.v.in generate_internal_asserts.py
	@WIDTH=$$(echo $* | cut -d'_' -f1 | tr -d 'W'); \
	DEPTH=$$(echo $* | cut -d'_' -f2 | tr -d 'D'); \
	FLAVOR=$$(echo $* | cut -d'_' -f3); \
	COMBO="W$${WIDTH}_D$${DEPTH}"; \
	run_name="check_$${COMBO}_$${FLAVOR}"; \
	$(MAKE) run/check_$${COMBO}_gold.il run/$${run_name}_gate.il && \
	gold="check_$${COMBO}_gold.il"; \
	gate="$${run_name}_gate.il"; \
	miter_file="$${run_name}_miter.v"; \
	sby_file="$${run_name}_custom_miter_with_extra_asserts.sby"; \
	mkdir -p internal_asserts; \
	sed -e "s/@WIDTH@/$$WIDTH/g" -e "s/@DEPTH@/$$DEPTH/g" miter.v.in > run/$$miter_file; \
	sed -e "s/@MITER@/$$miter_file/g" -e "s/@GOLD@/$$gold/g" -e "s/@GATE@/$$gate/g" \
	    -e "s#@EXPOSE_SRC@#../internal_asserts/expose_$${COMBO}_$${FLAVOR}.ys#g" \
	    -e "s#@DECLS_SRC@#../internal_asserts/decls_$${COMBO}_$${FLAVOR}.vh#g" \
	    -e "s#@PORTS_A_SRC@#../internal_asserts/ports_a_$${COMBO}_$${FLAVOR}.vh#g" \
	    -e "s#@PORTS_B_SRC@#../internal_asserts/ports_b_$${COMBO}_$${FLAVOR}.vh#g" \
	    -e "s#@ASSERTS_SRC@#../internal_asserts/asserts_$${COMBO}_$${FLAVOR}.vh#g" \
	    custom_miter_with_extra_asserts.sby.in > run/$$sby_file; \
	python3 generate_internal_asserts.py --combo $$COMBO --backend $$FLAVOR && \
	cd run && sby --sequential -f --prefix $${run_name}_custom_miter_with_extra_asserts $$sby_file

$(MUTATION_CHECK_EXTRA_ASSERTS_TARGETS): mutation-check-extra-asserts_%: run/check_%_netlist.v custom_miter_with_extra_asserts_mutation_check.sby.in miter.v.in mutate.tcl.in generate_internal_asserts.py
	@WIDTH=$$(echo $* | cut -d'_' -f1 | tr -d 'W'); \
	DEPTH=$$(echo $* | cut -d'_' -f2 | tr -d 'D'); \
	FLAVOR=$$(echo $* | cut -d'_' -f3); \
	COMBO="W$${WIDTH}_D$${DEPTH}"; \
	run_name="check_$${COMBO}_$${FLAVOR}"; \
	$(MAKE) run/check_$${COMBO}_gold.il run/$${run_name}_gate.il && \
	gold="check_$${COMBO}_gold.il"; \
	netlist="$${run_name}_netlist.v"; \
	mutated="$${run_name}_netlist_mutated.il"; \
	mutate_file="$${run_name}_mutate.tcl"; \
	miter_file="$${run_name}_miter.v"; \
	sby_file="$${run_name}_mutation_check_with_extra_asserts.sby"; \
	mkdir -p internal_asserts; \
	SEED=$$(od -An -N4 -tu4 /dev/urandom | tr -d ' '); \
	sed -e "s/@NETLIST@/$$netlist/g" -e "s/@MUTATED@/$$mutated/g" -e "s/@SEED@/$$SEED/g" -e "s/@NMUTATIONS@/10/g" mutate.tcl.in > run/$$mutate_file; \
	sed -e "s/@WIDTH@/$$WIDTH/g" -e "s/@DEPTH@/$$DEPTH/g" miter.v.in > run/$$miter_file; \
	sed -e "s/@MUTATED@/$$mutated/g" -e "s/@MITER@/$$miter_file/g" -e "s/@GOLD@/$$gold/g" \
	    -e "s#@EXPOSE_SRC@#../internal_asserts/expose_$${COMBO}_$${FLAVOR}.ys#g" \
	    -e "s#@DECLS_SRC@#../internal_asserts/decls_$${COMBO}_$${FLAVOR}.vh#g" \
	    -e "s#@PORTS_A_SRC@#../internal_asserts/ports_a_$${COMBO}_$${FLAVOR}.vh#g" \
	    -e "s#@PORTS_B_SRC@#../internal_asserts/ports_b_$${COMBO}_$${FLAVOR}.vh#g" \
	    -e "s#@ASSERTS_SRC@#../internal_asserts/asserts_$${COMBO}_$${FLAVOR}.vh#g" \
	    custom_miter_with_extra_asserts_mutation_check.sby.in > run/$$sby_file; \
	python3 generate_internal_asserts.py --combo $$COMBO --backend $$FLAVOR && \
	cd run && yosys -m slang -c $$mutate_file && \
	rm -rf $${run_name}_mutation_check_with_extra_asserts && \
	( sby -f --prefix $${run_name}_mutation_check_with_extra_asserts $$sby_file; true ) && \
	all_failed=1; \
	for f in $${run_name}_mutation_check_with_extra_asserts_task_*/status; do \
		st=$$(cut -d' ' -f1 $$f); \
		[ "$$st" = "FAIL" ] || all_failed=0; \
	done; \
	if [ "$$all_failed" = "1" ]; then \
		echo "mutation-check-extra-asserts $*: PASSED (miter correctly caught the injected gate mutation)"; \
	else \
		echo "mutation-check-extra-asserts $*: FAILED (expected FAIL from every task - the miter may not be checking anything!)"; \
		exit 1; \
	fi

clean:
	rm -rf run
