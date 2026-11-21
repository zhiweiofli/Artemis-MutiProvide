"""崩溃识别与恢复：游戏崩溃是「游戏缺陷」，不是「我们没跑成」。

规则（2026-11-21 定）：
- 每阶段结束查一次 crash buffer（FATAL EXCEPTION / ANR / 本进程死亡）
- 命中 → force-stop、重启、该阶段重跑一次（每款每阶段一次），判 CRASH 并保留崩溃原文
- 只重试一次：第二次还崩，就是稳定缺陷，如实记录
"""

from __future__ import annotations

import re
import subprocess
import time

DEVICE = "89FX09M9U"
CRASH_PATTERNS = ("FATAL EXCEPTION", "ANR in ", "Force finishing activity", "has died")


def adb(*args: str, timeout: int = 60) -> str:
    try:
        return subprocess.run(
            ["adb", "-s", DEVICE, *args], capture_output=True, text=True, timeout=timeout
        ).stdout
    except subprocess.TimeoutExpired:
        return ""


def crash_signature(package: str) -> str | None:
    """crash buffer 里与本包相关的最新一条崩溃摘要，没有则 None。"""
    out = adb("shell", "logcat", "-d", "-b", "crash", "-t", "400", timeout=90) or ""
    if package not in out and not any(p in out for p in CRASH_PATTERNS):
        return None
    lines = [ln for ln in out.splitlines() if any(p in ln for p in CRASH_PATTERNS) or package in ln]
    if not any(p in out for p in CRASH_PATTERNS):
        return None
    return "\n".join(lines[-12:])[:1500]


def classify(package: str, phase: str, verdict: str) -> str:
    """把阶段结果归类：CRASH（游戏崩了）优先于 FAIL/TIMEOUT。"""
    if verdict == "PASS":
        return "PASS"
    if crash_signature(package):
        return "CRASH"
    return verdict


def restart(package: str) -> bool:
    adb("shell", "am", "force-stop", package)
    time.sleep(2)
    adb("shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(6)
    return bool(foreground_package())


def foreground_package() -> str:
    out = adb("shell", "dumpsys", "window")
    m = re.search(r"mCurrentFocus=Window\{[^}]*?\s(\S+)/", out or "")
    return m.group(1) if m else ""
