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
src_dir = Path("src")
gold_prep_file = Path("gold_prepare.tcl")
gate_synth_file = Path("synth.tcl")
miter_file = Path("miter.v")
internal_assert_file = Path("miter_extra_asserts.sby.in")
tasks_sby_file = Path("tasks.sby.in")
miter_sby_file = Path("miter.sby.in")

pre_synth_file = Path("openroad/pre_synth.tcl")
post_synth_file = Path("openroad/post_synth.tcl")
config_mk_template_file = Path("openroad/config.mk.in")
constraint_sdc_file = Path("openroad/constraint.sdc")
timing_lib_file = Path("sky130/sky130_fd_sc_hd__tt_025C_1v80.lib")

TASKS_SBY_TEMPLATE = tasks_sby_file.read_text()
MITER_SBY_TEMPLATE = miter_sby_file.read_text()
INTERNAL_ASSERTS_SBY_TEMPLATE = internal_assert_file.read_text()
TASKS = parse_tasks(TASKS_SBY_TEMPLATE)


def _generate_rtl(name: str, count: int, build: Path) -> None:
    gen_src_dir = build / "gen_src"
    gen_build_dir = build / "gen_build"
    shutil.copytree(src_dir, gen_src_dir)

    core_file = gen_src_dir / "corescore.core"
    core_file.write_text(core_file.read_text().replace("##count##", str(count)))

    command = [
        "uv",
        "run",
        "--with",
        "fusesoc",
        "fusesoc",
        "--cores-root",
        ".",
        "run",
        "--work-root",
        str(gen_build_dir.resolve()),
        "--setup",
        "corescore",
    ]
    result = subprocess.run(command, cwd=gen_src_dir, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"fusesoc failed for {name}:\n{result.stderr}")

    for pattern in ("*.v", "*.vh", "*.hex"):
        for f in (*gen_src_dir.rglob(pattern), *gen_build_dir.rglob(pattern)):
            shutil.copy2(f, build / f.name)

    rtl_files = sorted(f.name for f in build.iterdir() if f.suffix in (".v", ".vh"))
    (build / "files.txt").write_text("\n".join(rtl_files) + "\n")

    shutil.rmtree(gen_src_dir)
    shutil.rmtree(gen_build_dir)


def _copy_tcl_fixing_flist(tcl_file: Path, build: Path) -> None:
    content = tcl_file.read_text().replace("-F ../../files.txt", "-F files.txt")
    (build / tcl_file).write_text(content)


def _write_sby_files(export_dir: Path, timeout: int) -> None:
    tasks_sby_final_content = TASKS_SBY_TEMPLATE.format(timeout=str(timeout))

    miter_sby_final_content = MITER_SBY_TEMPLATE.format(timeout=str(timeout))
    (export_dir / "miter.sby").write_text(
        tasks_sby_final_content + "\n\n" + miter_sby_final_content
    )

    internal_asserts_sby_final_content = INTERNAL_ASSERTS_SBY_TEMPLATE.format(
        timeout=str(timeout)
    )
    (export_dir / "miter_extra_asserts.sby").write_text(
        tasks_sby_final_content + "\n\n" + internal_asserts_sby_final_content
    )


class Setup(SetupBase):
    def __init__(self, count: int, timeout: int) -> None:
        self.params = {"count": count, "timeout": timeout}
        self.name = f"C{count}_T{timeout}"
        self.export_dir = run_dir / self.name

        if not self.export_dir.exists():
            with atomic_build_dir(self.export_dir) as build:
                _generate_rtl(self.name, count, build)

                # Copy Files
                _copy_tcl_fixing_flist(gold_prep_file, build)
                _copy_tcl_fixing_flist(gate_synth_file, build)
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

        _write_sby_files(self.export_dir, timeout)


class OrfsSetup(SetupBase):
    def __init__(self, count: int, timeout: int) -> None:
        self.params = {"count": count, "timeout": timeout}
        self.name = f"C{count}_T{timeout}"
        self.export_dir = run_dir / f"orfs_{self.name}"
        design_name = f"corescore_{self.name}"

        if not self.export_dir.exists():
            with atomic_build_dir(self.export_dir) as build:
                _generate_rtl(self.name, count, build)

                shutil.copy2(gold_prep_file, build / gold_prep_file)
                _copy_tcl_fixing_flist(gold_prep_file, build)

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
                    "TOP_MODULE": "corescore_de10_nano",
                    "DESIGN_INSTANCE_NAME": design_name,
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
                    "TOP_MODULE": "corescore_de10_nano",
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

        _write_sby_files(self.export_dir, timeout)


def main() -> None:
    benchmarks: list[Benchmark] = [
        ("Instance Count Scaling", lambda n: Setup(n, 60 * 15), TASKS, 1),
        (
            "Instance Count Scaling (ORFS)",
            lambda n: OrfsSetup(n, 60 * 15),
            TASKS,
            1,
        ),
    ]
    run_and_report(benchmarks, run_dir)


if __name__ == "__main__":
    main()
