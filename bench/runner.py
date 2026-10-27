import os
import re
import signal
import subprocess
import tempfile
import time
from pathlib import Path

SLICE = "bench.slice"
SLICE_DIR = Path(
    f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/{SLICE}"
)
CAP = []


def setup_mem_cap(cap):
    subprocess.run(
        [
            "systemctl",
            "--user",
            "set-property",
            "--runtime",
            SLICE,
            f"MemoryMax={cap}",
            "MemorySwapMax=0",
        ],
        check=True,
    )
    CAP[:] = ["systemd-run", "--user", "--scope", "--quiet", f"--slice={SLICE}", "--"]


def oom_kills():
    try:
        for ln in (SLICE_DIR / "memory.events").read_text().split("\n"):
            if ln.startswith("oom_kill "):
                return int(ln.split()[1])
    except OSError:
        pass
    return 0


OOM_WRAP = (
    'f=$1; shift; "$@"; rc=$?; cg=$(sed -n "s/^0:://p" /proc/self/cgroup); '
    'sed -n "s/^oom_kill //p" "/sys/fs/cgroup$cg/memory.events" > "$f"; exit $rc'
)


def capped(cmd):
    if not CAP:
        return cmd, None
    fd, path = tempfile.mkstemp(prefix="bench_oom_")
    os.close(fd)
    return CAP[:-1] + [
        "-p",
        "OOMPolicy=continue",
        "--",
        "sh",
        "-c",
        OOM_WRAP,
        "sh",
        path,
        *cmd,
    ], Path(path)


def oom_killed(oom_file, oom0):
    if oom_file is None:
        return False
    try:
        n = oom_file.read_text().strip()
        oom_file.unlink()
    except OSError:
        n = ""
    return int(n) > 0 if n.isdigit() else oom_kills() > oom0


def descendants(root):
    children = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            stat = Path(f"/proc/{d}/stat").read_text()
        except OSError:
            continue
        state, ppid = stat[stat.rindex(")") + 2 :].split()[:2]
        if state == "Z":
            continue
        children.setdefault(int(ppid), []).append(int(d))
    out, stack = [], [root]
    while stack:
        pid = stack.pop()
        out.append(pid)
        stack.extend(children.get(pid, []))
    return out


def kill_tree(root):
    own = os.getpgrp()
    for _ in range(10):
        alive = False
        for pid in descendants(root):
            try:
                g = os.getpgid(pid)
                if g != own:
                    os.killpg(g, signal.SIGKILL)
                os.kill(pid, signal.SIGKILL)
                alive = True
            except ProcessLookupError:
                pass
        if not alive:
            return
        time.sleep(0.2)


def become_subreaper():
    try:
        import ctypes

        ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0)
    except (OSError, AttributeError):
        pass


def reap_leftovers():
    for pid in descendants(os.getpid())[1:]:
        kill_tree(pid)
    deadline = time.time() + 10
    while time.time() < deadline:
        try:
            if os.waitpid(-1, os.WNOHANG)[0] == 0:
                if len(descendants(os.getpid())) == 1:
                    break
                time.sleep(0.1)
        except ChildProcessError:
            break


def run_sby(sby_file, tasks, timeout, mem_cap, odir):
    text = sby_file.read_text()
    out, sec = [], None
    for ln in text.split("\n"):
        m = re.match(r"^\[(\w+)\]", ln)
        if m:
            sec = m.group(1)
        elif sec == "files" and ln.strip() and not ln.strip().startswith("#"):
            *dest, src = ln.split()
            ln = " ".join([*dest, str(sby_file.parent / src)])
        elif sec == "options":
            ln = re.sub(r"\btimeout\s+\d+", f"timeout {timeout}", ln)
        out.append(ln)
    odir.mkdir(parents=True, exist_ok=True)
    sby = odir / sby_file.name
    sby.write_text("\n".join(out))
    modes = dict(re.findall(r"^(\S+): mode (\w+)", text, re.MULTILINE))
    procs, oomf = {}, {}
    oom0 = oom_kills()
    for task in tasks:
        d = odir / f"sby_{sby_file.stem}_{task}"
        cmd, oomf[task] = capped(["sby", "-f", "-d", str(d), str(sby), task])
        procs[task] = (
            subprocess.Popen(
                cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ),
            d,
        )
    t0 = time.time()
    status, ended, stopped = {}, {}, {}

    def status_of(d):
        st = next(
            (
                f
                for f in ("PASS", "FAIL", "UNKNOWN", "TIMEOUT", "ERROR")
                if (d / f).exists()
            ),
            None,
        )
        log = d / "logfile.txt"
        if (
            st is None
            and log.exists()
            and "Reached TIMEOUT" in log.read_text(errors="replace")
        ):
            st = "TIMEOUT"
        return st

    def killgroup(p):
        kill_tree(p.pid)
        p.wait()

    while len(ended) < len(procs):
        for task, (p, d) in procs.items():
            if task not in ended and p.poll() is not None:
                ended[task], status[task] = time.time() - t0, status_of(d)
                killgroup(p)
        decided = any(
            status.get(t) in ("PASS", "FAIL") and modes.get(t) == "prove" for t in ended
        )
        if decided or time.time() - t0 > timeout + 300:
            for task, (p, d) in procs.items():
                if task not in ended:
                    killgroup(p)
                    ended[task], status[task] = time.time() - t0, None
                    stopped[task] = (
                        "stopped: another engine decided first"
                        if decided
                        else "hard timeout"
                    )
        time.sleep(0.5)
    reap_leftovers()
    oom = {task: oom_killed(f, oom0) for task, f in oomf.items()}
    rows = []
    for task in procs:
        mode, st = modes.get(task, "?"), status[task]
        others_oom = any(v for t, v in oom.items() if t != task)
        result, reason = st or "ERROR", f"sby {st or 'no status'} (mode {mode})"
        if task in stopped:
            result, reason = "UNKNOWN", stopped[task]
        elif st in (None, "ERROR") and oom[task]:
            result, reason = (
                "ERROR",
                f"OOM: killed by the {mem_cap} memory cap (sby status {st})",
            )
        elif st == "TIMEOUT":
            result, reason = (
                "UNKNOWN",
                "timeout"
                + (
                    " (another engine of this case was OOM-killed)"
                    if others_oom
                    else ""
                ),
            )
        elif st == "PASS" and mode != "prove":
            result, reason = "UNKNOWN", f"{mode} passed (bounded, not a proof)"
        rows.append(
            {
                "task": task,
                "result": result,
                "reason": reason,
                "wall_secs": round(ended[task], 1),
            }
        )
    return rows


EQY_PREP = """hierarchy -auto-top
flatten
delete =A:blackbox
hierarchy -check
chformal -assert -remove
chformal -cover -remove
select -assert-none t:$assume t:$check t:$live t:$fair
rename -top top"""


def eqy_text(gold, gate, libs, pdr_timeout):
    libs = "".join(f"{lib}\n" for lib in libs)
    return f"""[options]
splitnets on

[gold]
read_rtlil {gold}
{EQY_PREP}

[gate]
{libs}read_rtlil {gate}
{EQY_PREP}

[collect *]
bind *

[strategy pdr]
use sby
engine abc pdr
timeout {pdr_timeout}
option vcd_sim on
"""


def ids_width(fields):
    for f in fields:
        if m := re.fullmatch(r"w=(-?\d+):(-?\d+)", f):
            return int(m.group(1)) - int(m.group(2)) + 1
    return 1


def eqy_outputs_compared(wd):
    ids = [ln.split() for ln in (wd / "gold.ids").read_text().split("\n")]
    tops = {t[0] for t in ids if len(t) > 2 and t[1] == "." and "A:top=1" in t}
    if len(tops) != 1:
        raise ValueError(
            f"{wd / 'gold.ids'}: expected one top module, found {sorted(tops) or 'none'}"
        )
    gold = {
        t[1]
        for t in ids
        if len(t) > 1 and t[0] in tops and "P=O" in t and ids_width(t) > 0
    }
    checked = set()
    for sv in (wd / "partitions").glob("*.sv"):
        block = re.search(
            r"`ifdef CHECK_OUTPUTS\n(.*?)`endif", sv.read_text(), re.DOTALL
        )
        if block:
            checked.update(
                re.findall(r'"assert"\) \\__po_(\S+)__assert ', block.group(1))
            )
    return gold, checked


def eqy_run(cfg, wd, log, jobs, limit, mem_cap):
    t0 = time.time()
    oom0 = oom_kills()
    cmd, oomf = capped(
        ["eqy", "-f", "-j", str(jobs), "-d", os.path.relpath(wd, cfg.parent), cfg.name]
    )
    with open(log, "w") as fh:
        p = subprocess.Popen(
            cmd,
            cwd=cfg.parent,
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        timed_out = False
        try:
            p.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            timed_out = True
        kill_tree(p.pid)
        p.wait()
    reap_leftovers()
    row = {"wall_secs": round(time.time() - t0, 1)}
    if oom_killed(oomf, oom0):
        return {
            **row,
            "result": "ERROR",
            "reason": f"OOM: killed by the {mem_cap} memory cap",
        }
    return {**row, **eqy_verdict(wd, log, timed_out)}


def eqy_verdict(wd, log, timed_out):
    targets = wd / "summary_targets.list"
    if not targets.exists():
        if timed_out:
            return {
                "result": "UNKNOWN",
                "reason": "timeout before partitioning finished",
            }
        last = [
            ln
            for ln in Path(log).read_text(errors="replace").split("\n")
            if "ERROR" in ln
        ][-1:]
        return {"result": "ERROR", "reason": last[0].strip() if last else f"see {log}"}

    status = {}
    for t in targets.read_text().split():
        part = t.split("/")[1]
        f = wd / t
        status[part] = (
            f.read_text().split()[0] if f.exists() and f.read_text().strip() else None
        )
    n = len(status)
    proven = sum(s == "PASS" for s in status.values())
    gold, checked = eqy_outputs_compared(wd)
    missing = sorted(
        o
        for o in gold
        if o not in checked and re.sub(r"\[\d+\]$", "", o) not in checked
    )
    summary = f"{proven}/{n} partitions proven, {len(gold)} output bits"
    if not gold or not n:
        return {"result": "ERROR", "reason": f"nothing compared: {summary}"}
    if missing:
        return {
            "result": "ERROR",
            "reason": f"{len(missing)} gold output bits not compared "
            f"(e.g. {', '.join(missing[:3])}); {summary}",
        }
    failed = sorted(k for k, s in status.items() if s == "FAIL")
    if failed:
        return {
            "result": "FAIL",
            "reason": f"partition counterexample in {', '.join(failed[:3])}"
            f"{' ...' if len(failed) > 3 else ''}; {summary}",
        }
    if timed_out or None in status.values():
        return {"result": "UNKNOWN", "reason": f"timeout; {summary}"}
    if "ERROR" in status.values():
        return {"result": "ERROR", "reason": f"strategy error; {summary}, see {wd}"}
    if proven < n:
        return {"result": "UNKNOWN", "reason": summary}
    return {"result": "PASS", "reason": summary}
