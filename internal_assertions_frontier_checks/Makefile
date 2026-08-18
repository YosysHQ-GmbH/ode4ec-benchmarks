SUBDIRS := $(filter-out _common/ sky130/,$(wildcard */))

.PHONY: all clean $(SUBDIRS) $(addsuffix run, $(SUBDIRS))

all: $(SUBDIRS)
clean: $(addsuffix run, $(SUBDIRS))

$(SUBDIRS):
	cd $@ && uv run find_max_parameter.py

$(addsuffix run, $(SUBDIRS)):
	rm -r $@
