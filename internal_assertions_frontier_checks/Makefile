SUBDIRS := $(filter-out _common/ sky130/,$(wildcard */))

.PHONY: all clean orfs $(SUBDIRS) $(addsuffix run, $(SUBDIRS))

all: $(SUBDIRS)
clean: $(addsuffix run, $(SUBDIRS))

$(SUBDIRS):
	cd $@ && uv run find_max_parameter.py

$(addsuffix run, $(SUBDIRS)):
	rm -r $@

orfs:
	python3 -c "from pathlib import Path; from _common.orfs import ensure_orfs_checkout; ensure_orfs_checkout(Path('.'))"
