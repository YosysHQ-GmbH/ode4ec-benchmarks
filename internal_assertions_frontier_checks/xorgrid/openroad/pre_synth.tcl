yosys -import

set design         $::env(TOP_MODULE)
set instance_name  $::env(DESIGN_INSTANCE_NAME)
set design_v       $::env(DESIGN_V)
set pre_synth_v    $::env(PRE_SYNTH_V)

plugin -i slang
read_slang ${design_v} --top ${design}
hierarchy -top ${design}

chformal -remove

flatten
opt_clean -purge

# ORFS keys its flow off DESIGN_NAME in config.mk, which must be unique per
# SIZE (xorgrid_S<n>) and so differs from the fixed module name ${design};
# rename to that instance name before handing off to ORFS.
yosys rename ${design} ${instance_name}

write_verilog -noattr ${pre_synth_v}
