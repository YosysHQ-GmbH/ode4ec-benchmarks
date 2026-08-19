# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "matplotlib>=3.11.1",
#     "polars>=1.43.2",
# ]
# ///
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _common.bench import (
    Benchmark,
    SetupBase,
    atomic_build_dir,
    parse_tasks,
    run_and_report,
)
from _common.generate_internal_asserts import generate_assert_files
from _common.orfs import cleanup_orfs_artifacts, ensure_orfs_checkout, run_orfs_synth

repo_root = Path(__file__).resolve().parent.parent

run_dir = Path("run")
gold_prep_file = Path("gold_prepare.tcl.in")
gate_synth_file = Path("synth.tcl.in")
miter_file = Path("miter.v")
internal_assert_file = Path("miter_extra_asserts.sby.in")
miter_sby_file = Path("miter.sby.in")
tasks_sby_file = Path("tasks.sby.in")

pre_synth_template_file = Path("openroad/pre_synth.tcl.in")
post_synth_file = Path("openroad/post_synth.tcl")
config_mk_template_file = Path("openroad/config.mk.in")
constraint_sdc_file = Path("openroad/constraint.sdc")
timing_lib_file = Path("sky130/sky130_fd_sc_hd__tt_025C_1v80.lib")

TASKS_SBY_TEMPLATE = tasks_sby_file.read_text()
MITER_SBY_TEMPLATE = miter_sby_file.read_text()
INTERNAL_ASSERTS_SBY_TEMPLATE = internal_assert_file.read_text()
GOLD_PREP_TEMPLATE = gold_prep_file.read_text()
SYNTH_TEMPLATE = gate_synth_file.read_text()
PRE_SYNTH_TEMPLATE = pre_synth_template_file.read_text()
TASKS = parse_tasks(TASKS_SBY_TEMPLATE)


def _render_tcl(template: str, WIDTH: int, LATENCY: int) -> str:
    return template.replace("@WIDTH@", str(WIDTH)).replace("@LATENCY@", str(LATENCY))


def _write_sby_files(export_dir: Path, WIDTH: int, timeout: int) -> None:
    tasks_sby_final_content = TASKS_SBY_TEMPLATE.format(timeout=str(timeout))

    miter_sby_final_content = MITER_SBY_TEMPLATE.format(WIDTH=str(WIDTH))
    (export_dir / "miter.sby").write_text(
        tasks_sby_final_content + "\n\n" + miter_sby_final_content
    )

    internal_asserts_sby_final_content = INTERNAL_ASSERTS_SBY_TEMPLATE.format(
        WIDTH=str(WIDTH)
    )
    (export_dir / "miter_extra_asserts.sby").write_text(
        tasks_sby_final_content + "\n\n" + internal_asserts_sby_final_content
    )


class Setup(SetupBase):
    def __init__(self, WIDTH: int, LATENCY: int, timeout: int) -> None:
        self.params = {"WIDTH": WIDTH, "LATENCY": LATENCY, "timeout": timeout}
        self.name = f"W{WIDTH}_L{LATENCY}_T{timeout}"
        self.export_dir = run_dir / self.name

        if not self.export_dir.exists():
            with atomic_build_dir(self.export_dir) as build:
                (build / "gold_prepare.tcl").write_text(
                    _render_tcl(GOLD_PREP_TEMPLATE, WIDTH, LATENCY)
                )
                command = ["yosys", "-m", "ghdl", "-c", "gold_prepare.tcl"]
                result = subprocess.run(
                    command, cwd=build, capture_output=True, text=True
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"gold_prepare.tcl failed for {self.name}:\n"
                        f"{result.stdout}\n{result.stderr}"
                    )

                (build / "synth.tcl").write_text(
                    _render_tcl(SYNTH_TEMPLATE, WIDTH, LATENCY)
                )
                command = ["yosys", "-m", "ghdl", "-c", "synth.tcl"]
                result = subprocess.run(
                    command, cwd=build, capture_output=True, text=True
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"synth.tcl failed for {self.name}:\n"
                        f"{result.stdout}\n{result.stderr}"
                    )

                shutil.copy2(miter_file, build / miter_file)

                generate_assert_files(
                    build / "gold.il",
                    build / "gate.il",
                    build / "expose.ys",
                    build / "decls.vh",
                    build / "ports_a.vh",
                    build / "ports_b.vh",
                    build / "asserts.vh",
                )

        _write_sby_files(self.export_dir, WIDTH, timeout)


class OrfsSetup(SetupBase):
    def __init__(self, WIDTH: int, LATENCY: int, timeout: int) -> None:
        self.params = {"WIDTH": WIDTH, "LATENCY": LATENCY, "timeout": timeout}
        self.name = f"W{WIDTH}_L{LATENCY}_T{timeout}"
        self.export_dir = run_dir / f"orfs_{self.name}"
        design_name = f"olo_base_arb_prio_{self.name}"

        if not self.export_dir.exists():
            with atomic_build_dir(self.export_dir) as build:
                (build / "gold_prepare.tcl").write_text(
                    _render_tcl(GOLD_PREP_TEMPLATE, WIDTH, LATENCY)
                )
                command = ["yosys", "-m", "ghdl", "-c", "gold_prepare.tcl"]
                result = subprocess.run(
                    command, cwd=build, capture_output=True, text=True
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"gold_prepare.tcl failed for {self.name}:\n"
                        f"{result.stdout}\n{result.stderr}"
                    )

                # ORFS gate synth
                orfs_flow_dir = ensure_orfs_checkout(repo_root)
                pre_synth_v = build / f"{design_name}_flat.v"

                (build / "pre_synth.tcl").write_text(
                    _render_tcl(PRE_SYNTH_TEMPLATE, WIDTH, LATENCY)
                )
                env = {
                    **os.environ,
                    "DESIGN_INSTANCE_NAME": design_name,
                    "PRE_SYNTH_V": str(pre_synth_v.resolve()),
                }
                command = ["yosys", "-m", "ghdl", "-c", "pre_synth.tcl"]
                result = subprocess.run(
                    command, cwd=build, env=env, capture_output=True, text=True
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"pre_synth.tcl failed for {self.name}:\n"
                        f"{result.stdout}\n{result.stderr}"
                    )

                config_mk = (
                    config_mk_template_file.read_text()
                    .replace("@DESIGN_NAME@", design_name)
                    .replace("@PRE_SYNTH_V@", str(pre_synth_v.resolve()))
                    .replace("@CONSTRAINT_SDC@", str(constraint_sdc_file.resolve()))
                )
                config_mk_path = build / "config.mk"
                config_mk_path.write_text(config_mk)

                orfs_netlist = run_orfs_synth(
                    orfs_flow_dir, config_mk_path.resolve(), design_name
                )

                env = {
                    **os.environ,
                    "DESIGN_INSTANCE_NAME": design_name,
                    "TIMING_LIB": str(timing_lib_file.resolve()),
                    "ORFS_NETLIST": str(orfs_netlist),
                    "WRAPPER_SYNTH": str((build / "gate.il").resolve()),
                }
                command = ["yosys", "-c", str(post_synth_file.resolve())]
                result = subprocess.run(
                    command, cwd=build, env=env, capture_output=True, text=True
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"post_synth.tcl failed for {self.name}:\n"
                        f"{result.stdout}\n{result.stderr}"
                    )

                cleanup_orfs_artifacts(orfs_flow_dir, design_name)

                shutil.copy2(miter_file, build / miter_file)

                generate_assert_files(
                    build / "gold.il",
                    build / "gate.il",
                    build / "expose.ys",
                    build / "decls.vh",
                    build / "ports_a.vh",
                    build / "ports_b.vh",
                    build / "asserts.vh",
                )

        _write_sby_files(self.export_dir, WIDTH, timeout)


def main() -> None:
    benchmarks: list[Benchmark] = [
        ("Width Scaling", lambda n: Setup(n, 1, 60), TASKS, 8),
        ("Latency Scaling", lambda n: Setup(16, n, 60), TASKS, 1),
        ("Width Scaling (ORFS)", lambda n: OrfsSetup(n, 1, 60), TASKS, 8),
        ("Latency Scaling (ORFS)", lambda n: OrfsSetup(16, n, 60), TASKS, 1),
    ]
    run_and_report(benchmarks, run_dir)


if __name__ == "__main__":
    main()
