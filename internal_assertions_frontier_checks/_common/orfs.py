import shutil
import subprocess
from pathlib import Path

ORFS_URL = "https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts.git"
ORFS_SPARSE_PATHS = (
    "flow/scripts",
    "flow/platforms/sky130hd",
    "flow/platforms/common",
    "flow/util",
    "flow/Makefile",
    "flow/settings.mk",
)
PLATFORM = "sky130hd"

ORFS_RESULT_SUBDIRS = ("results", "logs", "objects", "reports")


def ensure_orfs_checkout(root: Path) -> Path:
    orfs_dir = root / "orfs"
    if not (orfs_dir / ".git").exists():
        subprocess.run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                "--depth",
                "1",
                "--sparse",
                ORFS_URL,
                str(orfs_dir),
            ],
            check=True,
        )
        subprocess.run(
            ["git", "sparse-checkout", "set", *ORFS_SPARSE_PATHS],
            cwd=orfs_dir,
            check=True,
        )
        subprocess.run(["git", "checkout", "master"], cwd=orfs_dir, check=True)
    return orfs_dir / "flow"


def synth_target(design_name: str, platform: str = PLATFORM) -> str:
    return f"results/{platform}/{design_name}/base/1_2_yosys.v"


def run_orfs_synth(
    orfs_flow_dir: Path, design_config_mk: Path, design_name: str
) -> Path:
    yosys_exe = shutil.which("yosys")
    if yosys_exe is None:
        raise RuntimeError("yosys not found on PATH")

    target = synth_target(design_name)
    command = [
        "make",
        "-C",
        str(orfs_flow_dir),
        f"DESIGN_CONFIG={design_config_mk}",
        f"YOSYS_EXE={yosys_exe}",
        target,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ORFS synthesis failed for {design_config_mk}:\n"
            f"{result.stdout}\n{result.stderr}"
        )
    return orfs_flow_dir / target


def cleanup_orfs_artifacts(
    orfs_flow_dir: Path, design_name: str, platform: str = PLATFORM
) -> None:
    for subdir in ORFS_RESULT_SUBDIRS:
        path = orfs_flow_dir / subdir / platform / design_name
        if path.exists():
            shutil.rmtree(path)
