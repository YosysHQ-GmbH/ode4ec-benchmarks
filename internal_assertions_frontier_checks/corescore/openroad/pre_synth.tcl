yosys -import

set design         $::env(TOP_MODULE)
set instance_name  $::env(DESIGN_INSTANCE_NAME)
set pre_synth_v    $::env(PRE_SYNTH_V)

plugin -i slang
# --allow-use-before-declare: see gold_prepare.tcl
read_slang -F files.txt --top ${design} --allow-use-before-declare
hierarchy -top ${design}

chformal -remove

flatten
opt_clean -purge

# ORFS keys its flow off DESIGN_NAME in config.mk, which must be unique per
# instance count and so differs from the fixed module name ${design};
# rename to that instance name before handing off to ORFS.
yosys rename ${design} ${instance_name}

write_verilog -noattr ${pre_synth_v}
