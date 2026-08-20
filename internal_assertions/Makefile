SUBDIRS := $(dir $(wildcard */Makefile))

ORFS_DIR := orfs
ORFS_URL := https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git
ORFS_SPARSE_PATHS := flow/scripts flow/platforms/sky130hd flow/platforms/common flow/util flow/Makefile flow/settings.mk

TARGETS := clean sby sby-orfs synth openroad-synth \
	custom-miter custom-miter-orfs \
	custom-miter-extra-asserts custom-miter-extra-asserts-orfs \
	mutation-check mutation-check-orfs \
	mutation-check-extra-asserts mutation-check-extra-asserts-orfs \
	custom-miter-extra-asserts-mutation custom-miter-extra-asserts-mutation-orfs

.PHONY: all orfs report run-all run-incremental $(SUBDIRS) $(TARGETS) $(foreach t,$(TARGETS),$(addsuffix $(t),$(SUBDIRS)))

report:
	python3 report.py

run-all: $(filter-out clean,$(TARGETS))

run-incremental:
	python3 run_incremental.py

orfs:
	@if [ -d $(ORFS_DIR)/.git ]; then \
		echo "$(ORFS_DIR)/ already checked out; remove it to re-fetch"; \
	else \
		git clone --filter=blob:none --no-checkout --depth 1 --sparse $(ORFS_URL) $(ORFS_DIR) && \
		cd $(ORFS_DIR) && git sparse-checkout set $(ORFS_SPARSE_PATHS) && git checkout master; \
	fi

all : $(SUBDIRS)

$(SUBDIRS):
	$(MAKE) -C $@

define TARGET_RULE
$(1): $$(addsuffix $(1),$$(SUBDIRS))
$$(addsuffix $(1),$$(SUBDIRS)):
	@if grep -qE '^$(1):' $$(@:%$(1)=%)Makefile 2>/dev/null; then \
		$$(MAKE) -C $$(@:%$(1)=%) $(1) || echo "Warning: $(1) in $$@ failed"; \
	fi
endef

$(foreach t,$(TARGETS),$(eval $(call TARGET_RULE,$(t))))
