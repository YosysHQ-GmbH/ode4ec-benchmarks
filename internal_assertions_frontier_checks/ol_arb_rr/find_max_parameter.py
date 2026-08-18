# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "matplotlib>=3.11.1",
#     "polars>=1.43.2",
# ]
# ///
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

run_dir = Path("run")
gold_prep_file = Path("gold_prepare.tcl.in")
gate_synth_file = Path("synth.tcl.in")
miter_file = Path("miter.v")
internal_assert_file = Path("miter_extra_asserts.sby.in")
miter_sby_file = Path("miter.sby.in")
tasks_sby_file = Path("tasks.sby.in")

TASKS_SBY_TEMPLATE = tasks_sby_file.read_text()
MITER_SBY_TEMPLATE = miter_sby_file.read_text()
INTERNAL_ASSERTS_SBY_TEMPLATE = internal_assert_file.read_text()
GOLD_PREP_TEMPLATE = gold_prep_file.read_text()
SYNTH_TEMPLATE = gate_synth_file.read_text()
TASKS = parse_tasks(TASKS_SBY_TEMPLATE)


class Setup(SetupBase):
    def __init__(self, WIDTH: int, timeout: int) -> None:
        self.params = {"WIDTH": WIDTH, "timeout": timeout}
        self.name = f"W{WIDTH}_T{timeout}"
        self.export_dir = run_dir / self.name

        if not self.export_dir.exists():
            with atomic_build_dir(self.export_dir) as build:
                gold_prep_content = GOLD_PREP_TEMPLATE.replace("@WIDTH@", str(WIDTH))
                (build / "gold_prepare.tcl").write_text(gold_prep_content)
                command = ["yosys", "-m", "ghdl", "-c", "gold_prepare.tcl"]
                result = subprocess.run(
                    command, cwd=build, capture_output=True, text=True
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"gold_prepare.tcl failed for {self.name}:\n"
                        f"{result.stdout}\n{result.stderr}"
                    )

                synth_content = SYNTH_TEMPLATE.replace("@WIDTH@", str(WIDTH))
                (build / "synth.tcl").write_text(synth_content)
                command = ["yosys", "-m", "ghdl", "-c", "synth.tcl"]
                result = subprocess.run(
                    command, cwd=build, capture_output=True, text=True
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"synth.tcl failed for {self.name}:\n"
                        f"{result.stdout}\n{result.stderr}"
                    )

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

        tasks_sby_final_content = TASKS_SBY_TEMPLATE.format(timeout=str(timeout))

        miter_sby_final_content = MITER_SBY_TEMPLATE.format(WIDTH=str(WIDTH))
        (self.export_dir / "miter.sby").write_text(
            tasks_sby_final_content + "\n\n" + miter_sby_final_content
        )

        internal_asserts_sby_final_content = INTERNAL_ASSERTS_SBY_TEMPLATE.format(
            WIDTH=str(WIDTH)
        )
        (self.export_dir / "miter_extra_asserts.sby").write_text(
            tasks_sby_final_content + "\n\n" + internal_asserts_sby_final_content
        )


def main() -> None:
    benchmarks: list[Benchmark] = [
        ("Width Scaling", lambda n: Setup(n, 60), TASKS, 8),
    ]
    run_and_report(benchmarks, run_dir)


if __name__ == "__main__":
    main()
