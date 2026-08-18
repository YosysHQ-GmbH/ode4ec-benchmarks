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
src_dir = Path("src")
gold_prep_file = Path("gold_prepare.tcl")
gate_synth_file = Path("synth.tcl")
miter_file = Path("miter.v")
internal_assert_file = Path("miter_extra_asserts.sby.in")
miter_sby_file = Path("miter.sby.in")

MITER_SBY_TEMPLATE = miter_sby_file.read_text()
INTERNAL_ASSERTS_SBY_TEMPLATE = internal_assert_file.read_text()
TASKS = parse_tasks(MITER_SBY_TEMPLATE)


class Setup(SetupBase):
    def __init__(self, count: int, timeout: int) -> None:
        self.params = {"count": count, "timeout": timeout}
        self.name = f"C{count}_T{timeout}"
        self.export_dir = run_dir / self.name

        if not self.export_dir.exists():
            with atomic_build_dir(self.export_dir) as build:
                self._generate_rtl(count, build)

                # Copy Files
                self._copy_tcl_fixing_flist(gold_prep_file, build)
                self._copy_tcl_fixing_flist(gate_synth_file, build)
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

        # Sby file templates (rewritten every time, cheap, so `timeout` can
        # change across runs without invalidating the expensive build above)
        miter_sby_final_content = MITER_SBY_TEMPLATE.format(timeout=str(timeout))
        (self.export_dir / "miter.sby").write_text(miter_sby_final_content)

        internal_asserts_sby_final_content = INTERNAL_ASSERTS_SBY_TEMPLATE.format(
            timeout=str(timeout)
        )
        (self.export_dir / "miter_extra_asserts.sby").write_text(
            internal_asserts_sby_final_content
        )

    def _generate_rtl(self, count: int, build: Path) -> None:
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
        result = subprocess.run(
            command, cwd=gen_src_dir, capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"fusesoc failed for {self.name}:\n{result.stderr}")

        for pattern in ("*.v", "*.vh", "*.hex"):
            for f in (*gen_src_dir.rglob(pattern), *gen_build_dir.rglob(pattern)):
                shutil.copy2(f, build / f.name)

        rtl_files = sorted(f.name for f in build.iterdir() if f.suffix in (".v", ".vh"))
        (build / "files.txt").write_text("\n".join(rtl_files) + "\n")

        shutil.rmtree(gen_src_dir)
        shutil.rmtree(gen_build_dir)

    def _copy_tcl_fixing_flist(self, tcl_file: Path, build: Path) -> None:
        content = tcl_file.read_text().replace("-F ../../files.txt", "-F files.txt")
        (build / tcl_file).write_text(content)


def main() -> None:
    benchmarks: list[Benchmark] = [
        ("Instance Count Scaling", lambda n: Setup(n, 60 * 15), TASKS, 1),
    ]
    run_and_report(benchmarks, run_dir)


if __name__ == "__main__":
    main()
