"""空间预算：装之前先算清楚，不够就腾，腾不出就停手等用户确认。

规则（2026-11-21 定）：
- 预留 = 3 × 该游戏安装体积（体积取安装前能拿到的值：九游详情页容量文案，实测值回填台账）
- 不足时按「最近跑过的任务」倒序卸载 **我们自己装过的包**；系统包与九游自身永不动
- 卸载是破坏性动作，只发生在装前腾空间这一条路径上
"""

from __future__ import annotations

import re
import subprocess

DEVICE = "89FX09M9U"
RESERVE_MULTIPLIER = 3.0
#: 绝不卸载：九游自身与任何系统/预装包（只动我们记录过的第三方包）
NEVER_UNINSTALL = {"cn.ninegame.gamemanager", "cn.ninegame.launch.sample"}


def adb(*args: str, timeout: int = 60) -> str:
    try:
        return subprocess.run(
            ["adb", "-s", DEVICE, *args], capture_output=True, text=True, timeout=timeout
        ).stdout
    except subprocess.TimeoutExpired:
        return ""


def free_gb() -> float:
    out = adb("shell", "df", "/data")
    m = re.search(r"\s(\d+)\s+(\d+)\s+(\d+)\s+(\d+)%\s+/data", out)
    if not m:
        raise RuntimeError("读取 /data 可用空间失败")
    return round(int(m.group(3)) / 1024 / 1024, 2)


def parse_size_gb(text: str) -> float | None:
    """从九游详情页的容量文案估出 GB，如 '2179M' / '1.9G' / '2,179 MB'。"""
    if not text:
        return None
    t = text.replace(",", "").replace("，", "").strip().upper()  # 2,179 MB -> 2179MB
    m = re.search(r"([\d.]+)\s*(G|GB)", t)
    if m:
        return round(float(m.group(1)), 2)
    m = re.search(r"([\d.]+)\s*(M|MB)", t)
    if m:
        return round(float(m.group(1)) / 1024, 2)
    return None


def package_size_gb(package: str) -> float | None:
    """已安装包的占用（/data/app 下该包目录的实际大小）。"""
    out = adb("shell", "du", "-s", f"/data/app/*{package}*")
    m = re.search(r"(\d+)\s+", out or "")
    if not m:
        return None
    return round(int(m.group(1)) / 1024 / 1024, 2)


def installed_packages() -> set[str]:
    out = adb("shell", "pm", "list", "packages", "-3")
    return {line.removeprefix("package:").strip() for line in out.splitlines() if "package:" in line}


def required_gb(package_size: float | None) -> float:
    """装这套游戏需要的空间：3 × 体积；体积未知时按 2 GB 保守估。"""
    base = package_size if package_size and package_size > 0 else 2.0
    return round(base * RESERVE_MULTIPLIER, 2)


def verdict(free: float, need: float) -> str:
    if free >= need:
        return "ok"
    if free >= need * 0.5:
        return "reclaim"      # 腾一批旧包就够
    return "blocked"          # 差太多，腾包也救不了，交用户决定


def reclaim_order(history: list[str], protect: set[str] | None = None) -> list[str]:
    """可卸载候选：历史任务里我们装过、且不在保护名单里的包，最近的优先卸。

    ``history`` 由调用方按「最近优先」排好（台账倒序）。
    """
    protect = set(protect or set()) | NEVER_UNINSTALL
    seen, out = set(), []
    for pkg in history:
        if not pkg or pkg in seen or pkg in protect:
            continue
        seen.add(pkg)
        out.append(pkg)
    return out


def uninstall(package: str) -> bool:
    if package in NEVER_UNINSTALL:
        return False
    out = adb("shell", "pm", "uninstall", package, timeout=120)
    return "Success" in out


def ensure_capacity(package: str, need_gb: float, history: list[str]) -> dict:
    """确保装得下：够就 ok；不够就按顺序卸载旧包；仍不够就 blocked。"""
    free = free_gb()
    state = verdict(free, need_gb)
    removed: list[str] = []
    if state == "ok":
        return {"state": "ok", "free_gb": free, "need_gb": need_gb, "removed": removed}

    for pkg in reclaim_order(history, protect={package}):
        if free >= need_gb:
            break
        if pkg not in installed_packages():
            continue
        if uninstall(pkg):
            removed.append(pkg)
            free = free_gb()

    return {
        "state": "ok" if free >= need_gb else "blocked",
        "free_gb": free,
        "need_gb": need_gb,
        "removed": removed,
    }
