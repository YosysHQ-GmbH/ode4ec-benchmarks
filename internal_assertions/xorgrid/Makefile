I     ?= 32
O     ?= 32
C     ?= 16
F     ?= 8
N     ?= 6
D     ?= 4
SEED  ?= 0
SIZE  ?= 16
MAX_ASSERTS ?= 64

export TIMING_LIB = ../sky130/sky130_fd_sc_hd__tt_025C_1v80.lib
export TOP_MODULE = xorgrid

ORFS_HOME ?= $(abspath ../orfs)
export PLATFORM = sky130hd

COMBO         := S$(SIZE)
DESIGN_V      := run/check_$(COMBO)_design.v
GOLD_IL       := check_$(COMBO)_gold.il
YOSYS_GATE_IL := check_$(COMBO)_yosys_gate.il
ORFS_GATE_IL  := check_$(COMBO)_orfs_gate.il

ORFS_SYNTH_TARGET := results/$(PLATFORM)/xorgrid_$(COMBO)/base/1_2_yosys.v
export ORFS_NETLIST := $(ORFS_HOME)/flow/$(ORFS_SYNTH_TARGET)

GEN_ASSERTS_FLAGS := $(if $(MAX_ASSERTS),--max-asserts $(MAX_ASSERTS),)

.PHONY: clean synth openroad-synth custom-miter \
	custom-miter-orfs \
	custom-miter-extra-asserts custom-miter-extra-asserts-orfs \

$(DESIGN_V): gen_xorgrid.py
	@mkdir -p run
	uv run --with click --with numpy gen_xorgrid.py -I $(I) -O $(O) -C $(C) -W $(SIZE) -H $(SIZE) -F $(F) -N $(N) -D $(D) -S $(SEED) > $(DESIGN_V)

run/$(GOLD_IL): $(DESIGN_V) gold_prepare.tcl
	cd run && DESIGN_V=$(CURDIR)/$(DESIGN_V) GOLD_OUT=$(GOLD_IL) yosys -m slang -c ../gold_prepare.tcl

run/$(YOSYS_GATE_IL): $(DESIGN_V) synth.tcl
	cd run && DESIGN_V=$(CURDIR)/$(DESIGN_V) WRAPPER_SYNTH=$(YOSYS_GATE_IL) yosys -m slang -c ../synth.tcl

synth: run/$(YOSYS_GATE_IL)

run/$(ORFS_GATE_IL): $(DESIGN_V) openroad/pre_synth.tcl openroad/post_synth.tcl openroad/config.mk.in openroad/constraint.sdc
	@if [ ! -d "$(ORFS_HOME)/flow" ]; then \
		echo "No OpenROAD-flow-scripts checkout at $(ORFS_HOME). Run 'make orfs' from $(abspath ..) to fetch it, or pass ORFS_HOME=/path/to/OpenROAD-flow-scripts."; \
		exit 1; \
	fi
	mkdir -p openroad/run run
	sed -e "s/@SIZE@/$(COMBO)/g" \
	    -e "s#@PRE_SYNTH_V@#$(CURDIR)/openroad/run/$(COMBO)_flat.v#g" \
	    -e "s#@CONSTRAINT_SDC@#$(CURDIR)/openroad/constraint.sdc#g" \
	    openroad/config.mk.in > openroad/run/$(COMBO)_config.mk
	cd openroad && DESIGN_V=$(CURDIR)/$(DESIGN_V) PRE_SYNTH_V=$(CURDIR)/openroad/run/$(COMBO)_flat.v DESIGN_INSTANCE_NAME=xorgrid_$(COMBO) yosys -m slang -c pre_synth.tcl
	$(MAKE) -C $(ORFS_HOME)/flow DESIGN_CONFIG=$(CURDIR)/openroad/run/$(COMBO)_config.mk \
		YOSYS_EXE=$(shell command -v yosys) $(ORFS_SYNTH_TARGET)
	cd run && WRAPPER_SYNTH=$(ORFS_GATE_IL) DESIGN_INSTANCE_NAME=xorgrid_$(COMBO) yosys -c ../openroad/post_synth.tcl

openroad-synth: run/$(ORFS_GATE_IL)

custom-miter: run/$(GOLD_IL) run/$(YOSYS_GATE_IL) custom_miter.sby.in miter.v
	sed -e "s/@GOLD@/$(GOLD_IL)/g" -e "s/@GATE@/$(YOSYS_GATE_IL)/g" custom_miter.sby.in > run/check_$(COMBO)_yosys_custom_miter.sby
	cd run && sby -j 4 --statuscancels -f --prefix check_$(COMBO)_yosys_custom_miter check_$(COMBO)_yosys_custom_miter.sby

custom-miter-orfs: run/$(GOLD_IL) run/$(ORFS_GATE_IL) custom_miter.sby.in miter.v
	sed -e "s/@GOLD@/$(GOLD_IL)/g" -e "s/@GATE@/$(ORFS_GATE_IL)/g" custom_miter.sby.in > run/check_$(COMBO)_orfs_custom_miter.sby
	cd run && sby -j 4 --statuscancels -f --prefix check_$(COMBO)_orfs_custom_miter check_$(COMBO)_orfs_custom_miter.sby

run/check_$(COMBO)_yosys_internal_asserts.stamp: run/$(GOLD_IL) run/$(YOSYS_GATE_IL) generate_internal_asserts.py
	@mkdir -p internal_asserts
	python3 generate_internal_asserts.py --combo $(COMBO) --backend yosys $(GEN_ASSERTS_FLAGS)
	@touch $@

run/check_$(COMBO)_orfs_internal_asserts.stamp: run/$(GOLD_IL) run/$(ORFS_GATE_IL) generate_internal_asserts.py
	@mkdir -p internal_asserts
	python3 generate_internal_asserts.py --combo $(COMBO) --backend orfs $(GEN_ASSERTS_FLAGS)
	@touch $@

custom-miter-extra-asserts: run/check_$(COMBO)_yosys_internal_asserts.stamp custom_miter_with_extra_asserts.sby.in miter.v
	sed -e "s/@GOLD@/$(GOLD_IL)/g" -e "s/@GATE@/$(YOSYS_GATE_IL)/g" \
	    -e "s#@EXPOSE_SRC@#../internal_asserts/expose_$(COMBO)_yosys.ys#g" \
	    -e "s#@DECLS_SRC@#../internal_asserts/decls_$(COMBO)_yosys.vh#g" \
	    -e "s#@PORTS_A_SRC@#../internal_asserts/ports_a_$(COMBO)_yosys.vh#g" \
	    -e "s#@PORTS_B_SRC@#../internal_asserts/ports_b_$(COMBO)_yosys.vh#g" \
	    -e "s#@ASSERTS_SRC@#../internal_asserts/asserts_$(COMBO)_yosys.vh#g" \
	    custom_miter_with_extra_asserts.sby.in > run/check_$(COMBO)_yosys_custom_miter_with_extra_asserts.sby
	cd run && sby -j 4 --statuscancels -f --prefix check_$(COMBO)_yosys_custom_miter_with_extra_asserts check_$(COMBO)_yosys_custom_miter_with_extra_asserts.sby

custom-miter-extra-asserts-orfs: run/check_$(COMBO)_orfs_internal_asserts.stamp custom_miter_with_extra_asserts.sby.in miter.v
	sed -e "s/@GOLD@/$(GOLD_IL)/g" -e "s/@GATE@/$(ORFS_GATE_IL)/g" \
	    -e "s#@EXPOSE_SRC@#../internal_asserts/expose_$(COMBO)_orfs.ys#g" \
	    -e "s#@DECLS_SRC@#../internal_asserts/decls_$(COMBO)_orfs.vh#g" \
	    -e "s#@PORTS_A_SRC@#../internal_asserts/ports_a_$(COMBO)_orfs.vh#g" \
	    -e "s#@PORTS_B_SRC@#../internal_asserts/ports_b_$(COMBO)_orfs.vh#g" \
	    -e "s#@ASSERTS_SRC@#../internal_asserts/asserts_$(COMBO)_orfs.vh#g" \
	    custom_miter_with_extra_asserts.sby.in > run/check_$(COMBO)_orfs_custom_miter_with_extra_asserts.sby
	cd run && sby -j 4 --statuscancels -f --prefix check_$(COMBO)_orfs_custom_miter_with_extra_asserts check_$(COMBO)_orfs_custom_miter_with_extra_asserts.sby

clean:
	rm -rf run openroad/run internal_asserts
