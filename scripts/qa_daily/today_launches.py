#!/usr/bin/env python3
"""读取九游「即将上线」今天的首发清单（只读，不点下载/支付）。

用法：
    python3 scripts/qa_daily/today_launches.py [--json] [--require-download]

输出每个条目的 name / slot(如 "10:00 首发") / action(下载|预约|打开)。
--require-download 只保留当前已可下载的条目（19:00 后应当全部为「下载」）。
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
SLOT_RE = re.compile(r"(\d\d:\d\d)\s*(首发|更新|新活动|删档测试|公测|开放下载)")


def adb(*args: str, timeout: int = 30) -> str:
    try:
        return subprocess.run(
            ["adb", "-s", DEVICE, *args], capture_output=True, text=True, timeout=timeout
        ).stdout
    except subprocess.TimeoutExpired:
        return ""


def nodes() -> list[tuple[int, int, int, int, str]]:
    """(x1, y1, x2, y2, text) for every labelled node on screen."""
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
    return out


def band_rows(ns, tol: int = 24) -> dict[int, list[tuple[int, int, int, int, str]]]:
    rows: dict[int, list] = {}
    for n in ns:
        key = round(n[1] / tol) * tol
        rows.setdefault(key, []).append(n)
    return rows


def parse_cards(ns) -> list[dict]:
    """Cards are three stacked rows: name, genre, slot+action."""
    rows = band_rows(ns)
    action_rows = [y for y, items in rows.items() if sum(1 for i in items if i[4] in ACTIONS) >= 2]
    cards: list[dict] = []
    for ay in sorted(action_rows):
        slot_y = min((y for y in rows if 0 < ay - y <= 90), default=None)
        above = sorted((y for y in rows if slot_y is not None and 0 < slot_y - y <= 200), reverse=True)
        # Cards stack as name / genre / slot / action: the name is the second row up.
        name_y = above[1] if len(above) > 1 else (above[0] if above else None)
        if slot_y is None or name_y is None:
            continue
        for nx1, ny1, nx2, ny2, name in rows[name_y]:
            if len(name) < 2 or name in ACTIONS or SLOT_RE.search(name):
                continue
            def pick(row_y):
                hits = [t for x1, _, x2, _, t in rows[row_y] if x1 >= nx1 - 15 and x2 <= nx2 + 15]
                return " ".join(hits).strip()
            cards.append({
                "name": name,
                "slot": pick(slot_y),
                "action": pick(ay),
                # Card tap point: the image above the name (opens the detail page).
                "tap": [(nx1 + nx2) // 2, max(60, ny1 - 140)],
            })
    seen, uniq = set(), []
    for c in cards:
        if c["name"] in seen:
            continue
        seen.add(c["name"])
        uniq.append(c)
    return uniq


def open_today_tab() -> None:
    adb("shell", "am", "force-stop", PKG)
    time.sleep(1)
    adb("shell", "monkey", "-p", PKG, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(7)
    for _ in range(3):
        hits = [n for n in nodes() if n[4] in ("跳过", "跳过(1s)") or n[4].startswith("跳过")]
        if not hits:
            break
        x1, y1, x2, y2, _ = hits[0]
        adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
        time.sleep(3)
    today = [n for n in nodes() if n[4] == "今天"]
    if not today:
        raise SystemExit("找不到「今天」日期标签，页面结构可能变了")
    x1, y1, x2, y2, _ = today[0]
    adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))
    time.sleep(3)


def collect(max_swipes: int = 8) -> list[dict]:
    found: dict[str, dict] = {}
    last = None
    for _ in range(max_swipes):
        cards = parse_cards(nodes())
        for c in cards:
            found.setdefault(c["name"], c)
        sig = tuple(sorted(c["name"] for c in cards))
        if sig == last:
            break
        last = sig
        adb("shell", "input", "swipe", "950", "1553", "150", "1553", "400")
        time.sleep(1.3)
    return list(found.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--require-download", action="store_true")
    ap.add_argument("--max-swipes", type=int, default=8)
    args = ap.parse_args()

    open_today_tab()
    cards = collect(args.max_swipes)
    launches = [c for c in cards if "首发" in c.get("slot", "")]
    if args.require_download:
        launches = [c for c in launches if "下载" in c.get("action", "")]
    if args.json:
        print(json.dumps(launches, ensure_ascii=False, indent=1))
    else:
        for c in launches:
            print(f"{c['name']}\t{c['slot']}\t{c['action']}")
        print(f"共 {len(launches)} 款首发", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
