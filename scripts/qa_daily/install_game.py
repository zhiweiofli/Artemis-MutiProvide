#!/usr/bin/env python3
"""在九游里找到今天首发的某款游戏并完成下载安装，返回其包名。

用法：
    python3 scripts/qa_daily/install_game.py --name "幻想九霄" [--timeout-min 15]

流程：打开九游 → 今天首发列表 → 按名字点卡片 → 点「下载」→ 轮询 pm 包列表
直到出现新包。绝不点击任何付款/确认支付按钮。失败时退出码 2 并给出原因。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import today_launches as tl  # noqa: E402  (同目录工具，复用 UI dump/解析)

DOWNLOAD_LABELS = ("下载", "立即下载", "安装", "继续下载", "更新")
CONFIRM_LABELS = ("确定", "继续", "立即下载", "下载")


def installed_packages() -> set[str]:
    out = tl.adb("shell", "pm", "list", "packages", "-3")
    return {line.removeprefix("package:").strip() for line in out.splitlines() if "package:" in line}


def tap_bounds(x1: int, y1: int, x2: int, y2: int) -> None:
    tl.adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))


def tap_label(label: str, exact: bool = True) -> bool:
    for x1, y1, x2, y2, text in tl.nodes():
        if (text == label) if exact else (label in text):
            tap_bounds(x1, y1, x2, y2)
            return True
    return False


def clickable_nodes() -> list[tuple[int, int, int, int, str, str]]:
    """带 clickable 标记的节点表，用于找可点击容器（tl.nodes() 只有 5 元组）。"""
    import xml.etree.ElementTree as ET

    tl.TMP.mkdir(parents=True, exist_ok=True)
    tl.adb("shell", "uiautomator", "dump", "/sdcard/daily.xml")
    tl.adb("pull", "/sdcard/daily.xml", str(tl.TMP / "ui.xml"))
    root = ET.parse(tl.TMP / "ui.xml").getroot()
    out = []
    for n in root.iter("node"):
        text = (n.get("text") or "").strip()
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", n.get("bounds") or "")
        if not m:
            continue
        x1, y1, x2, y2 = (int(v) for v in m.groups())
        out.append((x1, y1, x2, y2, text, n.get("clickable") or "false"))
    return out


def clickable_center(ns, node) -> tuple[int, int]:
    """取包住该文案的最小可点击容器中心。九游底部动作条的文案是子节点，点文案本身有时不响应。"""
    x1, y1, x2, y2 = node[:4]
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    holders = [
        n for n in ns
        if n[5] == "true" and n[0] <= cx <= n[2] and n[1] <= cy <= n[3]
    ]
    if not holders:
        return cx, cy
    best = min(holders, key=lambda n: (n[2] - n[0]) * (n[3] - n[1]))
    return (best[0] + best[2]) // 2, (best[1] + best[3]) // 2


def download_evidence(timeout: float = 12.0) -> bool:
    """点完之后看有没有真的开始下载：底部出现百分比，或出现新的第三方包。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        ns = tl.nodes()
        if any("%" in n[4] for n in ns):
            return True
        time.sleep(2)
    return False


def tap_download_button(wait: float = 0.0) -> bool:
    """只点**详情页底部动作条**里的下载按钮。

    旧写法 `tap_label("下载", exact=False)` 会先命中顶部「下载管理」入口（2026-11-18 实测：
    装了三款全卡在这一步），所以这里改成「底部区域 + 精确/前缀匹配」。
    """
    hit = find_download_text(max_wait=wait)
    if hit is None:
        return False
    ns = tl.nodes()
    x, y = clickable_center(clickable_nodes(), hit)
    tl.adb("shell", "input", "tap", str(x), str(y))
    return True


def find_download_text(max_wait: float = 0.0):
    """在详情页底部动作条里找下载文案；max_wait>0 时轮询（详情页首屏要几秒才出按钮）。"""
    deadline = time.time() + max_wait
    while True:
        ns = tl.nodes()
        bottom = [n for n in ns if (n[1] + n[3]) // 2 > 1400]
        for want in DOWNLOAD_LABELS:
            for node in bottom:
                if node[4] == want:
                    return node
        for node in bottom:
            if node[4].startswith("下载") and node[4] != "下载管理":
                return node
        if time.time() >= deadline:
            return None
        time.sleep(2)


def back_to_top(swipes: int = 2) -> None:
    for _ in range(swipes):
        tl.adb("shell", "input", "swipe", "540", "700", "540", "1700", "300")
        time.sleep(0.8)


def locate_card(name: str, max_swipes: int = 8) -> dict | None:
    """回到列表顶部后逐屏查找「今天 · 首发」卡片。

    collect() 会一路下滑把明天/后天的场次也收进来，它记下的 tap 是**当时那一屏**的坐标，
    滑走后就失效（2026-11-18 实测：点了 3 屏之外的预约游戏）。这里改成「现查现点」：
    坐标只取当前这屏，命中立刻返回。
    """
    back_to_top()
    for _ in range(max_swipes):
        ns = tl.nodes()
        cards, _ = tl.parse_snapshot(ns)
        hit = next((c for c in cards if c["name"] == name and c["date"] == "今天"), None)
        if hit is not None:
            node = next(
                (n for n in ns if n[4] == name and abs((n[0] + n[2]) // 2 - hit["tap"][0]) < 80),
                None,
            )
            if node is not None:
                hit["tap"] = [(node[0] + node[2]) // 2, (node[1] + node[3]) // 2]
            return hit
        tl.adb("shell", "input", "swipe", "540", "1600", "540", "700", "350")
        time.sleep(1.4)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--timeout-min", type=float, default=15.0)
    args = ap.parse_args()

    before = installed_packages()
    if not before:
        print(json.dumps({"ok": False, "reason": "读不到设备上已安装的第三方包"}, ensure_ascii=False))
        return 2

    tl.open_launch_list()
    card = locate_card(args.name)
    if not card:
        print(json.dumps({"ok": False, "reason": f"今天首发列表里找不到《{args.name}》"}, ensure_ascii=False))
        return 2
    if "下载" not in card.get("action", "") and "打开" not in card.get("action", ""):
        print(json.dumps(
            {"ok": False, "reason": f"《{args.name}》当前状态是「{card.get('action')}」，还不能下载"},
            ensure_ascii=False,
        ))
        return 2

    x, y = card["tap"]
    tl.adb("shell", "input", "tap", str(x), str(y))
    time.sleep(3)
    find_download_text(max_wait=20)

    # 详情页：先点下载，再处理可能的「使用流量」确认弹窗
    tapped = False
    for attempt in range(3):
        if not tap_download_button(wait=15 if attempt == 0 else 5):
            break
        tapped = True
        if download_evidence():
            break
        time.sleep(2)
    if not tapped:
        print(json.dumps({"ok": False, "reason": "详情页上找不到下载按钮"}, ensure_ascii=False))
        return 2
    time.sleep(3)
    for label in CONFIRM_LABELS:
        if tap_label(label):
            break

    deadline = time.time() + args.timeout_min * 60
    new_pkg: str | None = None
    while time.time() < deadline:
        time.sleep(10)
        now = installed_packages()
        added = now - before
        if added:
            new_pkg = sorted(added)[0]
            break
        # 系统安装器弹窗
        for x1, y1, x2, y2, text in tl.nodes():
            if text in ("安装", "继续安装", "确定"):
                tap_bounds(x1, y1, x2, y2)
                break

    if not new_pkg:
        print(json.dumps(
            {"ok": False, "reason": f"{args.timeout_min} 分钟内未检测到新安装的包"}, ensure_ascii=False
        ))
        return 2

    print(json.dumps({"ok": True, "name": args.name, "package": new_pkg, "schedule": card.get("slot", "")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
