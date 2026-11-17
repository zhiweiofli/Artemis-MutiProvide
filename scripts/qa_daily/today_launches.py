#!/usr/bin/env python3
"""读取九游「即将上线 → 新游首发」的当日首发清单（只读，不点下载/支付）。

路径：首页「即将上线 · 更多」→ 列表页「新游首发」tab → 按日期分组的竖向列表。
早前版本读首页横向卡片，会把「明天」的首发算进「今天」，已废弃。

用法：
    python3 scripts/qa_daily/today_launches.py [--json] [--date 今天] [--require-download]

输出字段：name / date / slot("今天 10:00·首发") / kind(首发|更新|…) / action(下载|预约|…) / tap。
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

DEVICE = "89FX09M9U"
PKG = "cn.ninegame.gamemanager"
TMP = Path("/tmp/jiuyou_daily")

ACTIONS = {"下载", "预约", "打开", "继续", "云玩", "秒进游戏"}
DATE_HEADERS = {"今天", "明天", "后天", "大后天", "昨天", "前天"}
DATE_RE = re.compile(r"^\d{1,2}-\d{1,2}$")
SLOT_RE = re.compile(r"([^\s]+)\s+(\d\d:\d\d)[·・]\s*(首发|更新|新活动|删档测试|公测|开放下载|测试)")
RATING_RE = re.compile(r"^[\d.]+$")


def adb(*args: str, timeout: int = 30) -> str:
    try:
        return subprocess.run(
            ["adb", "-s", DEVICE, *args], capture_output=True, text=True, timeout=timeout
        ).stdout
    except subprocess.TimeoutExpired:
        return ""


def nodes() -> list[tuple[int, int, int, int, str]]:
    TMP.mkdir(parents=True, exist_ok=True)
    adb("shell", "uiautomator", "dump", "/sdcard/daily.xml")
    adb("pull", "/sdcard/daily.xml", str(TMP / "ui.xml"))
    root = ET.parse(TMP / "ui.xml").getroot()
    out = []
    for node in root.iter("node"):
        text = (node.get("text") or "").strip()
        if not text:
            continue
        m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds") or "")
        if not m:
            continue
        x1, y1, x2, y2 = (int(v) for v in m.groups())
        out.append((x1, y1, x2, y2, text))
    return sorted(out, key=lambda n: (n[1], n[0]))


def tap(x: float, y: float) -> None:
    adb("shell", "input", "tap", str(int(x)), str(int(y)))


def dismiss_splash() -> None:
    for _ in range(3):
        hits = [n for n in nodes() if n[4].startswith("跳过")]
        if not hits:
            return
        tap((hits[0][0] + hits[0][2]) / 2, (hits[0][1] + hits[0][3]) / 2)
        time.sleep(3)


def wait_for(labels: set[str], timeout: float = 25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        ns = nodes()
        hit = next((n for n in ns if n[4] in labels), None)
        if hit is not None:
            return hit, ns
        if any(n[4].startswith("跳过") for n in ns):
            dismiss_splash()
        time.sleep(2)
    return None, []


def open_launch_list() -> None:
    adb("shell", "am", "force-stop", PKG)
    time.sleep(1)
    adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(6)
    dismiss_splash()

    tab, _ = wait_for({"新游首发"}, timeout=2)
    if tab is None:
        section, ns = wait_for({"即将上线"})
        if section is None:
            raise SystemExit("等不到「即将上线」入口：页面改版或被开屏广告卡住")
        more = min(
            (n for n in ns if n[4] == "更多" and abs(n[1] - section[1]) < 120),
            key=lambda n: abs(n[1] - section[1]),
            default=None,
        )
        if more is None:
            raise SystemExit("首页找不到「即将上线 · 更多」入口")
        tap((more[0] + more[2]) / 2, (more[1] + more[3]) / 2)
        time.sleep(4)
        tab, _ = wait_for({"新游首发"}, timeout=10)
        if tab is None:
            raise SystemExit("列表页找不到「新游首发」tab")
    tap((tab[0] + tab[2]) / 2, (tab[1] + tab[3]) / 2)
    time.sleep(4)


def parse_snapshot(ns) -> tuple[list[dict], str | None]:
    """一屏一解析：日期分组 → 卡片（名称在上、按钮在右、场次行带「·首发」）。"""
    cards: list[dict] = []
    current: str | None = None
    for x1, y1, x2, y2, text in ns:
        if text in DATE_HEADERS or DATE_RE.match(text):
            current = text
            continue
        m = SLOT_RE.search(text)
        if not m:
            continue
        cx = (x1 + x2) / 2
        name_node = max(
            (
                n for n in ns
                if n[3] <= y1 and 0 < y1 - n[3] < 170
                and abs((n[0] + n[2]) / 2 - cx) < 420
                and n[4] not in ACTIONS and not RATING_RE.match(n[4])
                and "・" not in n[4] and len(n[4]) > 1
            ),
            key=lambda n: n[3],
            default=None,
        )
        if name_node is None:
            continue
        action = min(
            (
                n for n in ns
                if n[4] in ACTIONS and abs((n[1] + n[3]) / 2 - (y1 + y2) / 2) < 150
                and n[0] >= x2 - 40
            ),
            key=lambda n: abs((n[1] + n[3]) / 2 - (y1 + y2) / 2),
            default=None,
        )
        slot_date = m.group(1)
        cards.append({
            "name": name_node[4],
            "date": slot_date if DATE_RE.match(slot_date) else (current or slot_date),
            "slot": f"{slot_date} {m.group(2)}·{m.group(3)}",
            "kind": m.group(3),
            "starts_at": m.group(2),
            "action": action[4] if action else "",
            "tap": [(name_node[0] + name_node[2]) // 2, max(60, name_node[1] - 120)],
        })
    return cards, current


def collect(max_swipes: int = 10) -> list[dict]:
    found: dict[str, dict] = {}
    idle = 0
    for _ in range(max_swipes):
        cards, _ = parse_snapshot(nodes())
        fresh = [c for c in cards if c["name"] not in found]
        for c in fresh:
            found[c["name"]] = c
        idle = idle + 1 if not fresh else 0
        if idle >= 2:
            break
        adb("shell", "input", "swipe", "540", "1600", "540", "700", "350")
        time.sleep(1.4)
    return list(found.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--date", default="今天")
    ap.add_argument("--require-download", action="store_true")
    ap.add_argument("--max-swipes", type=int, default=10)
    args = ap.parse_args()

    open_launch_list()
    cards = collect(args.max_swipes)
    launches = [c for c in cards if c["kind"] == "首发" and c["date"] in (args.date, "今天")]
    if args.date == "今天":
        launches = [c for c in launches if c["date"] == "今天"]
    if args.require_download:
        launches = [c for c in launches if "下载" in c["action"]]
    launches.sort(key=lambda c: (c["date"], c["starts_at"]))
    if args.json:
        print(json.dumps(launches, ensure_ascii=False, indent=1))
    else:
        for c in launches:
            print(f"{c['name']}\t{c['slot']}\t{c['action']}")
        print(f"共 {len(launches)} 款首发（{args.date}）", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
