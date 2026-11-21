#!/usr/bin/env python3
"""每日质检的单实例锁：一轮没跑完，第二轮不许开始。

2026-11-18 的教训：19:00 那轮还在跑，20:30 的补跑守卫看到台账没记录就又启动了一次，
虽然它自己发现设备被占用后停手，但期间误 force-stop 了正在跑的游戏的 E 阶段。

锁用 fcntl.flock 放在 /tmp，进程退出自动释放；另外用 pgrep 兜底识别「锁文件所在磁盘被清」
或「上一轮被 kill -9 留下的僵尸锁」。
"""

from __future__ import annotations

import errno
import fcntl
import os
import subprocess
from pathlib import Path

LOCK_PATH = Path("/tmp/artemis_qa_daily.lock")
RUNNER_PATTERN = "qa_daily/run_games.py|qa_daily/install_game.py"


def _open_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    return open(LOCK_PATH, "a+", encoding="utf-8")


def try_acquire(tag: str = "") -> tuple[bool, str]:
    """返回 (是否拿到锁, 说明)。拿不到时说明里带占用者信息。"""
    fh = _open_lock()
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as e:
        if e.errno not in (errno.EACCES, errno.EAGAIN):
            raise
        fh.seek(0)
        holder = fh.read().strip() or "未知"
        fh.close()
        return False, f"另一轮正在跑（{holder}）"

    fh.seek(0)
    fh.truncate()
    fh.write(f"pid={os.getpid()} tag={tag}")
    fh.flush()
    # 锁文件句柄挂在进程上，退出即释放
    try_acquire._fh = fh  # type: ignore[attr-defined]
    return True, "ok"


def running_processes() -> list[str]:
    """正在跑的质检脚本进程（pgrep 兜底）。"""
    try:
        out = subprocess.run(
            ["pgrep", "-fl", RUNNER_PATTERN], capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    mine = f"pid={os.getpid()}"
    return [
        line for line in out.splitlines()
        if line.strip() and mine not in line
    ]


def busy_reason() -> str | None:
    """有另一轮在跑时返回可读原因，否则 None。"""
    procs = running_processes()
    if procs:
        return "另一轮质检正在跑：" + " | ".join(p.strip()[:90] for p in procs[:2])
    if LOCK_PATH.exists():
        fh = _open_lock()
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            fh.seek(0)
            return "另一轮质检持有锁：" + (fh.read().strip() or "未知")
        finally:
            fh.close()
    return None
