#!/usr/bin/env python3
"""corescore's RTL for COUNT cores, generated with FuseSoC and copied flat to OUT, listed in OUT/files.txt.
usage: gen.py COUNT OUT"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FUSESOC = "fusesoc==2.4.7"     # pinned: the generated files depend on it

count, out = sys.argv[1], Path(sys.argv[2])
with tempfile.TemporaryDirectory() as t:
    gsrc, gbuild = Path(t) / "src", Path(t) / "build"
    shutil.copytree(Path(__file__).resolve().parent / "src", gsrc)
    core = gsrc / "corescore.core"
    core.write_text(core.read_text().replace("##count##", count))
    subprocess.run(["uv", "run", "--no-project", "--with", FUSESOC, "fusesoc", "--cores-root", ".", "run",
                    "--work-root", str(gbuild), "--setup", "corescore"], cwd=gsrc, check=True)
    for pattern in ("*.v", "*.vh", "*.hex"):
        for f in (*gsrc.rglob(pattern), *gbuild.rglob(pattern)):
            shutil.copy2(f, out / f.name)
(out / "files.txt").write_text("\n".join(sorted(f.name for f in out.iterdir() if f.suffix in (".v", ".vh"))) + "\n")
