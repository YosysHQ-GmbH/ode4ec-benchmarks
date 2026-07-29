SUBDIRS := $(dir $(wildcard fft_*/Makefile))

TARGETS := clean sby sby-orfs eqy eqy-orfs synth openroad-synth \
	custom-miter custom-miter-orfs \
	custom-miter-extra-asserts custom-miter-extra-asserts-orfs \
	mutation-check mutation-check-orfs \
	custom-miter-extra-asserts-mutation custom-miter-extra-asserts-mutation-orfs

.PHONY: all $(SUBDIRS) $(TARGETS) $(foreach t,$(TARGETS),$(addsuffix $(t),$(SUBDIRS)))

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
