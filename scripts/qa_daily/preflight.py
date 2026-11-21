#!/usr/bin/env python3
"""每日质检的前置检查：设备、网络、手机可用空间、连续执行天数。

用法：python3 scripts/qa_daily/preflight.py [--json]
退出码：0 = 允许执行，2 = 不满足前置条件（原因写在输出里）。

台账：docs/qa_daily/ledger.json 记录实际执行过的日期；「连续执行天数」按
截止昨天的连续天数计算，今天再跑就是 streak+1，必须 < 4。
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlock  # noqa: E402  (同目录的单实例锁)

DEVICE = "89FX09M9U"
MIN_FREE_GB = 10.0
MAX_CONSECUTIVE_DAYS = 4
LEDGER = Path(__file__).resolve().parents[2] / "docs" / "qa_daily" / "ledger.json"


def sh(*args: str, timeout: int = 30) -> str:
    try:
        return subprocess.run(
            ["adb", "-s", DEVICE, *args], capture_output=True, text=True, timeout=timeout
        ).stdout
    except subprocess.TimeoutExpired:
        return ""


def connected() -> bool:
    try:
        out = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=20).stdout
    except subprocess.TimeoutExpired:
        return False
    return any(line.split()[:2] == [DEVICE, "device"] for line in out.splitlines())


def network_ok() -> tuple[bool, str]:
    out = sh("shell", "ping", "-c", "2", "-W", "2", "connect.rom.miui.com", timeout=20)
    m = re.search(r"(\d+)% packet loss", out)
    if not m:
        return False, "ping 无响应"
    loss = int(m.group(1))
    rtt = re.search(r"rtt min/avg/max/mdev = ([\d.]+)/([\d.]+)", out)
    return loss == 0, f"丢包 {loss}%" + (f"，平均 {rtt.group(2)}ms" if rtt else "")


def free_gb() -> float | None:
    out = sh("shell", "df", "/data")
    m = re.search(r"\s(\d+)\s+(\d+)\s+(\d+)\s+(\d+)%\s+/data", out)
    if not m:
        return None
    available_kb = int(m.group(3))
    return round(available_kb / 1024 / 1024, 1)


def consecutive_days(today: dt.date) -> int:
    try:
        runs = json.loads(LEDGER.read_text())["runs"]
    except Exception:
        return 0
    dates = {r["date"] for r in runs if isinstance(r.get("date"), str)}
    streak, cursor = 0, today - dt.timedelta(days=1)
    while cursor.isoformat() in dates:
        streak += 1
        cursor -= dt.timedelta(days=1)
    return streak


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--today", default=None, help="覆盖当天日期（YYYY-MM-DD），仅用于测试")
    args = ap.parse_args()

    today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
    device = connected()
    net, net_note = network_ok() if device else (False, "设备未连接")
    free = free_gb() if device else None
    streak = consecutive_days(today)
    busy = runlock.busy_reason()

    reasons = []
    if not device:
        reasons.append(f"设备 {DEVICE} 未连接")
    if device and not net:
        reasons.append(f"网络异常（{net_note}）")
    if free is not None and free < MIN_FREE_GB:
        reasons.append(f"手机可用空间 {free} GB < {MIN_FREE_GB} GB")
    if free is None and device:
        reasons.append("读取不到 /data 可用空间")
    if busy:
        reasons.append(busy)
    if streak + 1 >= MAX_CONSECUTIVE_DAYS:
        reasons.append(f"连续执行第 {streak + 1} 天，已达上限 {MAX_CONSECUTIVE_DAYS} 次，今天不跑")

    result = {
        "date": today.isoformat(),
        "device_connected": device,
        "network_ok": net,
        "network_note": net_note,
        "free_gb": free,
        "busy": bool(busy),
        "consecutive_days_before_today": streak,
        "would_be_run_number": streak + 1,
        "allowed": not reasons,
        "reasons": reasons,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(f"{'允许执行' if result['allowed'] else '不满足前置条件'}")
        for line in reasons:
            print(f"- {line}")
    return 0 if not reasons else 2


if __name__ == "__main__":
    sys.exit(main())
