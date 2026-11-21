"""设备清场与收尾：别让上一个游戏拖慢/污染下一个。

规则（2026-11-21 定）：
- 开跑前把往期任务的游戏 force-stop 掉，释放内存和 CPU
- 每轮结束把本轮游戏 force-stop（**默认不卸载**，卸载只发生在装前腾空间）
"""

from __future__ import annotations

import re
import subprocess

DEVICE = "89FX09M9U"
#: 不是游戏，别碰
SKIP = {"cn.ninegame.gamemanager", "cn.ninegame.launch.sample"}


def adb(*args: str, timeout: int = 60) -> str:
    try:
        return subprocess.run(
            ["adb", "-s", DEVICE, *args], capture_output=True, text=True, timeout=timeout
        ).stdout
    except subprocess.TimeoutExpired:
        return ""


def mem_available_gb() -> float | None:
    out = adb("shell", "cat", "/proc/meminfo")
    m = re.search(r"MemAvailable:\s+(\d+) kB", out or "")
    return round(int(m.group(1)) / 1024 / 1024, 2) if m else None


def foreground() -> str:
    out = adb("shell", "dumpsys", "window")
    m = re.search(r"mCurrentFocus=Window\{[^}]*?\s(\S+)/", out or "")
    return m.group(1) if m else ""


def force_stop(packages: list[str]) -> list[str]:
    """force-stop 一批包；返回真正停掉的（不存在的包跳过）。"""
    installed = {
        line.removeprefix("package:").strip()
        for line in adb("shell", "pm", "list", "packages", "-3").splitlines()
        if "package:" in line
    }
    stopped = []
    for pkg in packages:
        if not pkg or pkg in SKIP or pkg not in installed:
            continue
        adb("shell", "am", "force-stop", pkg)
        stopped.append(pkg)
    return stopped


def quiesce(history: list[str]) -> dict:
    """开跑前清场：停掉往期游戏，回到桌面，记一次内存。"""
    before = mem_available_gb()
    stopped = force_stop(list(dict.fromkeys(history)))
    adb("shell", "input", "keyevent", "KEYCODE_HOME")
    return {
        "foreground_before": foreground(),
        "stopped": stopped,
        "mem_available_gb_before": before,
        "mem_available_gb_after": mem_available_gb(),
    }


def teardown(packages: list[str]) -> dict:
    """收尾：本轮游戏 force-stop（不卸载），回到桌面。"""
    before = mem_available_gb()
    stopped = force_stop(list(dict.fromkeys(packages)))
    adb("shell", "input", "keyevent", "KEYCODE_HOME")
    return {
        "stopped": stopped,
        "mem_available_gb_before": before,
        "mem_available_gb_after": mem_available_gb(),
    }
