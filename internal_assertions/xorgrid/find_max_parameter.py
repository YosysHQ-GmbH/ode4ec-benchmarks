import os
import re
import shutil
import subprocess
import sys
from collections import deque
from collections.abc import Iterator
from pathlib import Path
from typing import TextIO

from generate_internal_asserts import generate_assert_files

run_dir = Path("run")
gold_prep_file = Path("gold_prepare.tcl")
gate_synth_file = Path("synth.tcl")
miter_file = Path("miter.v")
internal_assert_file = Path("miter_extra_asserts.sby.in")
miter_sby_file = Path("miter.sby.in")
verilog_file = Path("xorgrid.v")


def live_window_stream(stream: TextIO, num_lines: int = 5, indent: int = 1) -> None:
    window = deque(maxlen=num_lines)
    lines_currently_displayed = 0
    prefix = "    " * indent

    for line in stream:
        term_width = shutil.get_terminal_size((80, 20)).columns
        clean_line = line.rstrip("\n")

        available_width = term_width - len(prefix)
        if len(clean_line) > available_width:
            clean_line = clean_line[: max(available_width - 1, 0)]

        window.append(prefix + clean_line)

        if lines_currently_displayed > 0:
            sys.stdout.write(f"\033[{lines_currently_displayed}A")

        for w_line in window:
            sys.stdout.write(f"\033[2K\r{w_line}\n")

        sys.stdout.flush()
        lines_currently_displayed = len(window)

    if lines_currently_displayed > 0:
        sys.stdout.write(f"\033[{lines_currently_displayed}A")
        for _ in range(lines_currently_displayed):
            sys.stdout.write("\033[2K\n")
        sys.stdout.write(f"\033[{lines_currently_displayed}A")
        sys.stdout.flush()


class Setup:
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
        self.name = f"I{I}_O{O}_C{C}_W{W}_H{H}_F{F}_N{N}_D{D}_S{S}_T{timeout}"
        self.export_dir = run_dir / self.name
        if self.export_dir.exists():
            return
        self.export_dir.mkdir(parents=True)

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
            print("Errors:\n", result.stderr)
            return

        with open(self.export_dir / verilog_file, "w") as f:
            f.write(result.stdout)

        # Copy Files
        shutil.copy2(gold_prep_file, self.export_dir / gold_prep_file)
        shutil.copy2(gate_synth_file, self.export_dir / gate_synth_file)
        shutil.copy2(miter_file, self.export_dir / miter_file)

        # Gold Prep
        command = ["yosys", "-m", "slang", "-c", gold_prep_file]
        result = subprocess.run(
            command, cwd=self.export_dir, capture_output=True, text=True
        )
        if result.stderr:
            print("Errors:\n", result.stderr)
            return

        # Gate Synth
        command = ["yosys", "-m", "slang", "-c", gate_synth_file]
        result = subprocess.run(
            command, cwd=self.export_dir, capture_output=True, text=True
        )
        if result.stderr:
            print("Errors:\n", result.stderr)
            return

        # Sby file templates
        miter_sby_content = miter_sby_file.read_text()
        miter_sby_final_content = miter_sby_content.format(
            I=str(I), O=str(O), C=str(C), timeout=str(timeout)
        )
        (self.export_dir / "miter.sby").write_text(miter_sby_final_content)

        internal_asserts_sby_content = internal_assert_file.read_text()
        internal_asserts_sby_final_content = internal_asserts_sby_content.format(
            I=str(I), O=str(O), C=str(C), timeout=str(timeout)
        )
        (self.export_dir / "miter_extra_asserts.sby").write_text(
            internal_asserts_sby_final_content
        )

        # Generate Internal Asserts
        gold_netlist_file = self.export_dir / "gold.il"
        gate_netlist_file = self.export_dir / "gate.il"

        expose_file = self.export_dir / "expose.ys"
        decls_file = self.export_dir / "decls.vh"
        ports_a_file = self.export_dir / "ports_a.vh"
        ports_b_file = self.export_dir / "ports_b.vh"
        asserts_file = self.export_dir / "asserts.vh"

        generate_assert_files(
            gold_netlist_file,
            gate_netlist_file,
            expose_file,
            decls_file,
            ports_a_file,
            ports_b_file,
            asserts_file,
        )

    def read_marker_file(self, task: str, sby_file: str) -> tuple[str, str, str, str]:
        MARKER_FILES = ["PASS", "FAIL", "UNKNOWN", "ERROR", "TIMEOUT", "CANCELLED"]
        PROCESS_TIME_PATTERN = re.compile(
            r"^Elapsed process time \[H:MM:SS \(secs\)\]: (\d+:\d+:\d+) \((\d+)\)$",
            flags=re.MULTILINE,
        )
        CLOCK_TIME_PATTERN = re.compile(
            r"^Elapsed clock time \[H:MM:SS \(secs\)\]: (\d+:\d+:\d+) \((\d+)\)$",
            flags=re.MULTILINE,
        )

        for marker in MARKER_FILES:
            marker_path = self.export_dir / f"{sby_file.split('.')[0]}_{task}" / marker
            if os.path.exists(marker_path):
                content = marker_path.read_text(encoding="utf-8-sig")
                match_proccess = PROCESS_TIME_PATTERN.search(content)
                match_clock = CLOCK_TIME_PATTERN.search(content)
                proccess_time = "---"
                clock_time = "---"
                if match_proccess:
                    proccess_time = match_proccess.group(1)
                if match_clock:
                    clock_time = match_clock.group(1)
                return (self.name, marker, proccess_time, clock_time)
        return (self.name, "---", "---", "---")

    def run_task(self, task: str, sby_file: str) -> tuple[str, str, str, str]:
        result = self.read_marker_file(task, sby_file)
        if result[1] != "---":
            return result
        # else:
        # return (self.name, "---", "---", "---")

        command = [
            "sby",
            "-j",
            "4",
            "--statuscancels",
            "-f",
            sby_file,
            task,
        ]
        process = subprocess.Popen(
            command,
            cwd=self.export_dir,
            stdout=subprocess.PIPE,
            text=True,
        )

        live_window_stream(process.stdout, num_lines=10)
        process.wait()

        return self.read_marker_file(task, sby_file)


def merge_by_name(list_m, list_i):
    dict_m = {
        name: (results, clock, process) for name, results, clock, process in list_m
    }
    dict_i = {
        name: (results, clock, process) for name, results, clock, process in list_i
    }

    names_m = [name for name, *_ in list_m]
    names_i = [name for name, *_ in list_i]
    all_names = names_m + [n for n in names_i if n not in dict_m]

    merged = []
    for name in all_names:
        results_m, clock_m, process_m = dict_m.get(name, ("---", "---", "---"))
        results_i, clock_i, process_i = dict_i.get(name, ("---", "---", "---"))
        merged.append(
            (name, results_m, clock_m, process_m, results_i, clock_i, process_i)
        )

    return merged


def run_benchmark(setup_gen: Callable[[], Iterator[int]]) -> None:
    tasks = ["btor", "bitwuzla", "abc", "aiger"]
    end_results_miter = {}
    end_results_internal_asserts = {}
    for task in tasks:
        results_miter = [("", "PASS", "---", "---")]
        results_internal_asserts = [("", "PASS", "---", "---")]

        task_setups = setup_gen()
        while (
            results_miter[-1][1] == "PASS" or results_internal_asserts[-1][1] == "PASS"
        ):
            setup = next(task_setups)

            if results_miter[-1][1] == "PASS":
                print(f"Running: MI {task} {setup.name}")
                results_miter.append(setup.run_task(task, "miter.sby"))
            if results_internal_asserts[-1][1] == "PASS":
                print(f"Running: IA {task} {setup.name}")
                results_internal_asserts.append(
                    setup.run_task(task, "miter_extra_asserts.sby")
                )

        end_results_miter[task] = results_miter[1:]
        end_results_internal_asserts[task] = results_internal_asserts[1:]
    print()

    for task in tasks:
        print(f"=== Task {task} ===")
        print(
            "Task\t\t\t\t\t\tResult (MI)\tResult (IA)\tProcess (MI)\tProcess (IA)\tClock (MI)\tClock (IA)"
        )
        merged = merge_by_name(
            end_results_miter[task], end_results_internal_asserts[task]
        )

        for name, result_m, clock_m, process_m, result_a, clock_a, process_a in merged:
            print(
                f"{name}\t\t{result_m}\t\t{result_a}\t\t{process_m}\t\t{process_a}\t\t{clock_m}\t\t{clock_a}"
            )
        print()


def main() -> None:
    print("=== Tile Grid Scaling ===")

    def tile_grid_setup():
        i = 2
        while True:
            setup = Setup(16, 16, 16, i, i, 8, 6, 4, 0, 60 * 10)
            yield setup
            i += 1

    run_benchmark(lambda: tile_grid_setup())

    print("=== Control Bit Scaling ===")

    def control_bit_setup():
        i = 1
        while True:
            setup = Setup(16, 16, 2**i, i * 2, i * 2, 8, 6, 4, 0, 60 * 10)
            yield setup
            i += 1

    run_benchmark(lambda: control_bit_setup())

    print("=== Max Distance Scaling ===")

    def max_distance_setup():
        i = 1
        while True:
            setup = Setup(16, 16, 16, i * 2, i * 2, 8, 6, 2**i, 0, 60 * 10)
            yield setup
            i += 1

    run_benchmark(lambda: max_distance_setup())

    print("=== Input bits Scaling ===")

    def input_bits_setup():
        i = 1
        while True:
            setup = Setup(i, i, i, 12, 12, 8, 8, 4, 0, 60 * 10)
            yield setup
            i += 1

    run_benchmark(lambda: input_bits_setup())


if __name__ == "__main__":
    main()
