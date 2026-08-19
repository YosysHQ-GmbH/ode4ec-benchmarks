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
gold_prep_file = Path("gold_prepare.tcl")
gate_synth_file = Path("synth.tcl")
miter_file = Path("miter.v")
internal_assert_file = Path("miter_extra_asserts.sby.in")
miter_sby_file = Path("miter.sby.in")
tasks_sby_file = Path("tasks.sby.in")
verilog_file = Path("xorgrid.v")

pre_synth_file = Path("openroad/pre_synth.tcl")
post_synth_file = Path("openroad/post_synth.tcl")
config_mk_template_file = Path("openroad/config.mk.in")
constraint_sdc_file = Path("openroad/constraint.sdc")
timing_lib_file = Path("sky130/sky130_fd_sc_hd__tt_025C_1v80.lib")

TASKS_SBY_TEMPLATE = tasks_sby_file.read_text()
MITER_SBY_TEMPLATE = miter_sby_file.read_text()
INTERNAL_ASSERTS_SBY_TEMPLATE = internal_assert_file.read_text()
TASKS = parse_tasks(TASKS_SBY_TEMPLATE)


class Setup(SetupBase):
    def __init__(
        self,
        I: int,
        O: int,
        C: int,
        W: int,
        H: int,
        F: int,
        N: int,
        D: int,
        S: int,
        timeout: int,
    ) -> None:
        self.params = {
            "I": I,
            "O": O,
            "C": C,
            "W": W,
            "H": H,
            "F": F,
            "N": N,
            "D": D,
            "S": S,
            "timeout": timeout,
        }
        self.name = f"I{I}_O{O}_C{C}_W{W}_H{H}_F{F}_N{N}_D{D}_S{S}_T{timeout}"
        self.export_dir = run_dir / self.name

        if not self.export_dir.exists():
            with atomic_build_dir(self.export_dir) as build:
                # Generate xorgrid
                command = [
                    "uv",
                    "run",
                    "--with",
                    "click",
                    "xorgrid.py",
                    "-I",
                    f"{I}",
                    "-O",
                    f"{O}",
                    "-C",
                    f"{C}",
                    "-W",
                    f"{W}",
                    "-H",
                    f"{H}",
                    "-F",
                    f"{F}",
                    "-N",
                    f"{N}",
                    "-D",
                    f"{D}",
                    "-S",
                    f"{S}",
                ]
                result = subprocess.run(command, capture_output=True, text=True)
                if result.stderr:
                    raise RuntimeError(
                        f"xorgrid.py failed for {self.name}:\n{result.stderr}"
                    )

                with open(build / verilog_file, "w") as f:
                    f.write(result.stdout)

                # Copy Files
                shutil.copy2(gold_prep_file, build / gold_prep_file)
                shutil.copy2(gate_synth_file, build / gate_synth_file)
                shutil.copy2(miter_file, build / miter_file)

                # Gold Prep
                command = ["yosys", "-m", "slang", "-c", gold_prep_file]
                result = subprocess.run(
                    command, cwd=build, capture_output=True, text=True
                )
                if result.stderr:
                    raise RuntimeError(
                        f"gold_prepare.tcl failed for {self.name}:\n{result.stderr}"
                    )

                # Gate Synth
                command = ["yosys", "-m", "slang", "-c", gate_synth_file]
                result = subprocess.run(
                    command, cwd=build, capture_output=True, text=True
                )
                if result.stderr:
                    raise RuntimeError(
                        f"synth.tcl failed for {self.name}:\n{result.stderr}"
                    )

                # Generate Internal Asserts
                generate_assert_files(
                    build / "gold.il",
                    build / "gate.il",
                    build / "expose.ys",
                    build / "decls.vh",
                    build / "ports_a.vh",
                    build / "ports_b.vh",
                    build / "asserts.vh",
                )

        _write_sby_files(self.export_dir, I, O, C, timeout)


class OrfsSetup(SetupBase):
    def __init__(
        self,
        I: int,
        O: int,
        C: int,
        W: int,
        H: int,
        F: int,
        N: int,
        D: int,
        S: int,
        timeout: int,
    ) -> None:
        self.params = {
            "I": I,
            "O": O,
            "C": C,
            "W": W,
            "H": H,
            "F": F,
            "N": N,
            "D": D,
            "S": S,
            "timeout": timeout,
        }
        self.name = f"I{I}_O{O}_C{C}_W{W}_H{H}_F{F}_N{N}_D{D}_S{S}_T{timeout}"
        self.export_dir = run_dir / f"orfs_{self.name}"
        design_name = f"xorgrid_{self.name}"

        if not self.export_dir.exists():
            with atomic_build_dir(self.export_dir) as build:
                # Generate xorgrid (same RTL as the yosys flavor)
                command = [
                    "uv",
                    "run",
                    "--with",
                    "click",
                    "xorgrid.py",
                    "-I",
                    f"{I}",
                    "-O",
                    f"{O}",
                    "-C",
                    f"{C}",
                    "-W",
                    f"{W}",
                    "-H",
                    f"{H}",
                    "-F",
                    f"{F}",
                    "-N",
                    f"{N}",
                    "-D",
                    f"{D}",
                    "-S",
                    f"{S}",
                ]
                result = subprocess.run(command, capture_output=True, text=True)
                if result.stderr:
                    raise RuntimeError(
                        f"xorgrid.py failed for {self.name}:\n{result.stderr}"
                    )

                with open(build / verilog_file, "w") as f:
                    f.write(result.stdout)

                shutil.copy2(gold_prep_file, build / gold_prep_file)

                # Gold Prep (same as the yosys flavor)
                command = ["yosys", "-m", "slang", "-c", gold_prep_file]
                result = subprocess.run(
                    command, cwd=build, capture_output=True, text=True
                )
                if result.stderr:
                    raise RuntimeError(
                        f"gold_prepare.tcl failed for {self.name}:\n{result.stderr}"
                    )

                # ORFS gate synth
                orfs_flow_dir = ensure_orfs_checkout(repo_root)
                pre_synth_v = build / f"{design_name}_flat.v"

                env = {
                    **os.environ,
                    "TOP_MODULE": "xorgrid",
                    "DESIGN_INSTANCE_NAME": design_name,
                    "DESIGN_V": str((build / verilog_file).resolve()),
                    "PRE_SYNTH_V": str(pre_synth_v.resolve()),
                }
                command = ["yosys", "-m", "slang", "-c", str(pre_synth_file.resolve())]
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
                    .replace("@SIZE@", self.name)
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
                    "TOP_MODULE": "xorgrid",
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

                # Copy Files
                shutil.copy2(miter_file, build / miter_file)

                # Generate Internal Asserts
                generate_assert_files(
                    build / "gold.il",
                    build / "gate.il",
                    build / "expose.ys",
                    build / "decls.vh",
                    build / "ports_a.vh",
                    build / "ports_b.vh",
                    build / "asserts.vh",
                )

        _write_sby_files(self.export_dir, I, O, C, timeout)


def _write_sby_files(export_dir: Path, I: int, O: int, C: int, timeout: int) -> None:
    tasks_sby_final_content = TASKS_SBY_TEMPLATE.format(
        I=str(I), O=str(O), C=str(C), timeout=str(timeout)
    )

    miter_sby_final_content = MITER_SBY_TEMPLATE.format(
        I=str(I), O=str(O), C=str(C), timeout=str(timeout)
    )
    (export_dir / "miter.sby").write_text(
        tasks_sby_final_content + "\n\n" + miter_sby_final_content
    )

    internal_asserts_sby_final_content = INTERNAL_ASSERTS_SBY_TEMPLATE.format(
        I=str(I), O=str(O), C=str(C), timeout=str(timeout)
    )
    (export_dir / "miter_extra_asserts.sby").write_text(
        tasks_sby_final_content + "\n\n" + internal_asserts_sby_final_content
    )


def main() -> None:
    benchmarks: list[Benchmark] = [
        (
            "Tile Grid Scaling",
            lambda n: Setup(16, 16, 16, n, n, 8, 6, 4, 0, 600),
            TASKS,
            4,
            2,  # min_n: W*H*F >= I=16 needs n*n*8 >= 16, i.e. n >= 2
        ),
        (
            "Control Bit Scaling",
            lambda n: Setup(16, 16, 2**n, n * 2, n * 2, 8, 6, 4, 0, 600),
            TASKS,
            1,
        ),
        (
            "Max Distance Scaling",
            lambda n: Setup(16, 16, 16, n * 2, n * 2, 8, 6, 2**n, 0, 600),
            TASKS,
            1,
        ),
        (
            "Tile Grid Scaling (ORFS)",
            lambda n: OrfsSetup(16, 16, 16, n, n, 8, 6, 4, 0, 600),
            TASKS,
            2,
            2,  # min_n: W*H*F >= I=16 needs n*n*8 >= 16, i.e. n >= 2
        ),
        (
            "Control Bit Scaling (ORFS)",
            lambda n: OrfsSetup(16, 16, 2**n, n * 2, n * 2, 8, 6, 4, 0, 600),
            TASKS,
            1,
        ),
        (
            "Max Distance Scaling (ORFS)",
            lambda n: OrfsSetup(16, 16, 16, n * 2, n * 2, 8, 6, 2**n, 0, 600),
            TASKS,
            1,
        ),
    ]
    run_and_report(benchmarks, run_dir)


if __name__ == "__main__":
    main()
