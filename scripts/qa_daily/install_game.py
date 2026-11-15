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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--timeout-min", type=float, default=15.0)
    args = ap.parse_args()

    before = installed_packages()
    if not before:
        print(json.dumps({"ok": False, "reason": "读不到设备上已安装的第三方包"}, ensure_ascii=False))
        return 2

    tl.open_today_tab()
    cards = tl.collect(max_swipes=10)
    card = next((c for c in cards if c["name"] == args.name), None)
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
    time.sleep(5)

    # 详情页：先点下载，再处理可能的「使用流量」确认弹窗
    tapped = tap_label("下载", exact=False) or tap_label("安装", exact=False)
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
