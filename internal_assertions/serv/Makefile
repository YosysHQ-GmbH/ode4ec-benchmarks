export TIMING_LIB=../sky130/sky130_fd_sc_hd__tt_025C_1v80.lib
export FLIST=../files.txt
export TOP_MODULE=serv_top

YOSYS_WRAPPER_SYNTH := gate_out_yosys.il
ORFS_WRAPPER_SYNTH  := gate_out_orfs.il

ORFS_HOME       ?= $(abspath ../orfs)
export PLATFORM     = sky130hd
export PRE_SYNTH_V  = $(CURDIR)/openroad/run/serv_flat.v
ORFS_SYNTH_TARGET    = results/$(PLATFORM)/$(TOP_MODULE)/base/1_2_yosys.v
export ORFS_NETLIST = $(ORFS_HOME)/flow/$(ORFS_SYNTH_TARGET)

.PHONY: eqy sby clean synth openroad-synth custom-miter mutation-check \
	eqy-orfs sby-orfs custom-miter-orfs mutation-check-orfs \
	custom-miter-extra-asserts custom-miter-extra-asserts-mutation


run/$(YOSYS_WRAPPER_SYNTH): synth.tcl
	mkdir -p run
	cd run && WRAPPER_SYNTH=$(YOSYS_WRAPPER_SYNTH) yosys -m slang -c ../synth.tcl
	cd run && WRAPPER_SYNTH=$(YOSYS_WRAPPER_SYNTH) yosys -m slang -c ../gold_prepare.tcl

synth: run/$(YOSYS_WRAPPER_SYNTH)

run/$(ORFS_WRAPPER_SYNTH): openroad/pre_synth.tcl openroad/post_synth.tcl openroad/config.mk openroad/constraint.sdc
	@if [ ! -d "$(ORFS_HOME)/flow" ]; then \
		echo "No OpenROAD-flow-scripts checkout at $(ORFS_HOME). Run 'make orfs' from $(abspath ..) to fetch it, or pass ORFS_HOME=/path/to/OpenROAD-flow-scripts."; \
		exit 1; \
	fi
	mkdir -p openroad/run run
	cd openroad && yosys -m slang -c pre_synth.tcl
	$(MAKE) -C $(ORFS_HOME)/flow DESIGN_CONFIG=$(CURDIR)/openroad/config.mk \
		YOSYS_EXE=$(shell command -v yosys) $(ORFS_SYNTH_TARGET)
	cd run && WRAPPER_SYNTH=$(ORFS_WRAPPER_SYNTH) yosys -c ../openroad/post_synth.tcl
	cd run && WRAPPER_SYNTH=$(YOSYS_WRAPPER_SYNTH) yosys -m slang -c ../gold_prepare.tcl

openroad-synth: run/$(ORFS_WRAPPER_SYNTH)

eqy: run/$(YOSYS_WRAPPER_SYNTH)
	ln -sf $(YOSYS_WRAPPER_SYNTH) run/gate_out.il
	cd run &&	eqy -f -d check_eqy_yosys ../check.eqy

eqy-orfs: run/$(ORFS_WRAPPER_SYNTH)
	ln -sf $(ORFS_WRAPPER_SYNTH) run/gate_out.il
	cd run &&	eqy -f -d check_eqy_orfs ../check.eqy

sby: run/$(YOSYS_WRAPPER_SYNTH)
	ln -sf $(YOSYS_WRAPPER_SYNTH) run/gate_out.il
	cd run && sby --sequential -f --prefix check_sby_yosys ../check.sby

sby-orfs: run/$(ORFS_WRAPPER_SYNTH)
	ln -sf $(ORFS_WRAPPER_SYNTH) run/gate_out.il
	cd run && sby --sequential -f --prefix check_sby_orfs ../check.sby

custom-miter: run/$(YOSYS_WRAPPER_SYNTH)
	ln -sf $(YOSYS_WRAPPER_SYNTH) run/gate_out.il
	cd run && sby --sequential -f --prefix check_custom_miter_yosys ../custom_miter.sby

custom-miter-orfs: run/$(ORFS_WRAPPER_SYNTH)
	ln -sf $(ORFS_WRAPPER_SYNTH) run/gate_out.il
	cd run && sby --sequential -f --prefix check_custom_miter_orfs ../custom_miter.sby

mutation-check: run/$(YOSYS_WRAPPER_SYNTH)
	ln -sf $(YOSYS_WRAPPER_SYNTH) run/gate_out.il
	cd run && yosys -c ../mutate.tcl && \
	rm -rf mutation_check_yosys && \
	( sby -f --prefix mutation_check_yosys ../custom_miter_mutation_check.sby; true ) && \
	all_failed=1; \
	for f in mutation_check_yosys_task_*/status; do \
		st=$$(cut -d' ' -f1 $$f); \
		[ "$$st" = "FAIL" ] || all_failed=0; \
	done; \
	if [ "$$all_failed" = "1" ]; then \
		echo "mutation-check: PASSED (miter correctly caught the injected gate mutation)"; \
	else \
		echo "mutation-check: FAILED (expected FAIL from every task - the miter may not be checking anything!)"; \
		exit 1; \
	fi

mutation-check-orfs: run/$(ORFS_WRAPPER_SYNTH)
	ln -sf $(ORFS_WRAPPER_SYNTH) run/gate_out.il
	cd run && yosys -c ../mutate.tcl && \
	rm -rf mutation_check_orfs && \
	( sby -f --prefix mutation_check_orfs ../custom_miter_mutation_check.sby; true ) && \
	all_failed=1; \
	for f in mutation_check_orfs_task_*/status; do \
		st=$$(cut -d' ' -f1 $$f); \
		[ "$$st" = "FAIL" ] || all_failed=0; \
	done; \
	if [ "$$all_failed" = "1" ]; then \
		echo "mutation-check-orfs: PASSED (miter correctly caught the injected gate mutation)"; \
	else \
		echo "mutation-check-orfs: FAILED (expected FAIL from every task - the miter may not be checking anything!)"; \
		exit 1; \
	fi

custom-miter-extra-asserts: run/$(YOSYS_WRAPPER_SYNTH)
	ln -sf $(YOSYS_WRAPPER_SYNTH) run/gate_out.il
	cd run && sby --sequential -f --prefix check_custom_miter_extra_asserts_yosys ../custom_miter_with_extra_asserts.sby

custom-miter-extra-asserts-orfs: run/$(ORFS_WRAPPER_SYNTH)
	ln -sf $(ORFS_WRAPPER_SYNTH) run/gate_out.il
	python3 generate_internal_asserts.py --backend orfs
	cd run && sby --sequential -f --prefix check_custom_miter_extra_asserts_orfs ../custom_miter_with_extra_asserts_orfs.sby

custom-miter-extra-asserts-mutation: run/$(YOSYS_WRAPPER_SYNTH)
	ln -sf $(YOSYS_WRAPPER_SYNTH) run/gate_out.il
	cd run && yosys -c ../mutate.tcl && \
	rm -rf mutation_check_extra_asserts_yosys && \
	( sby -f --prefix mutation_check_extra_asserts_yosys ../custom_miter_with_extra_asserts_mutation_check.sby; true ) && \
	all_failed=1; \
	for f in mutation_check_extra_asserts_yosys_task_*/status; do \
		st=$$(cut -d' ' -f1 $$f); \
		[ "$$st" = "FAIL" ] || all_failed=0; \
	done; \
	if [ "$$all_failed" = "1" ]; then \
		echo "custom-miter-extra-asserts-mutation: PASSED (miter correctly caught the injected gate mutation)"; \
	else \
		echo "custom-miter-extra-asserts-mutation: FAILED (expected FAIL from every task - the miter may not be checking anything!)"; \
		exit 1; \
	fi

custom-miter-extra-asserts-mutation-orfs: run/$(ORFS_WRAPPER_SYNTH)
	ln -sf $(ORFS_WRAPPER_SYNTH) run/gate_out.il
	python3 generate_internal_asserts.py --backend orfs
	cd run && yosys -c ../mutate.tcl && \
	rm -rf mutation_check_extra_asserts_orfs && \
	( sby -f --prefix mutation_check_extra_asserts_orfs ../custom_miter_with_extra_asserts_mutation_check_orfs.sby; true ) && \
	all_failed=1; \
	for f in mutation_check_extra_asserts_orfs_task_*/status; do \
		st=$$(cut -d' ' -f1 $$f); \
		[ "$$st" = "FAIL" ] || all_failed=0; \
	done; \
	if [ "$$all_failed" = "1" ]; then \
		echo "custom-miter-extra-asserts-mutation-orfs: PASSED (miter correctly caught the injected gate mutation)"; \
	else \
		echo "custom-miter-extra-asserts-mutation-orfs: FAILED (expected FAIL from every task - the miter may not be checking anything!)"; \
		exit 1; \
	fi

clean:
	rm -rf run
