#!/usr/bin/env python3
"""每日质检的单一入口：prepare → 取单 → 安装 → 跑测 → 收尾。

这一层是纯脚本（不经过模型）：设备状态、空间预算、清场、安装、收尾都由它执行，
只有 BC/D/E 的游戏内决策交给 Artemis（run_games.py 起子进程）。

退出码契约：
  0 跑完（哪怕有游戏 FAIL/TIMEOUT）
  2 前置条件不满足（设备/网络/空间/连续天数）
  3 另一轮正在跑
  4 当日没有可下载的首发
  5 安装全部失败
  6 反复崩溃导致中止

用法：python3 scripts/qa_daily/run_daily.py [--budget-min 180] [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

from preflight import (  # noqa: E402  (同目录：设备/网络/空间/连续天数)
    connected,
    consecutive_days,
    free_gb,
    network_ok,
)
import runlock  # noqa: E402
from rules import capacity, cleanup  # noqa: E402

HISTORY = ROOT / "docs" / "qa_daily" / "history.json"
OUT_ROOT = ROOT / "traces"


def sh(*args: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args], cwd=str(ROOT), capture_output=True, text=True, timeout=timeout
    )


def load_history() -> dict:
    try:
        return json.loads(HISTORY.read_text())
    except Exception:
        return {"runs": []}


def recent_packages(history: dict, limit: int = 20) -> list[str]:
    pkgs: list[str] = []
    for run in reversed(history.get("runs", [])):
        pkgs.extend(run.get("packages", []))
    seen, out = set(), []
    for p in pkgs:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return out[:limit]


def resolve_installed_package(card: dict) -> str | None:
    """卡片已经是「打开」时，点进游戏从前台读出包名，读完立刻停掉。"""
    tap = card.get("tap") or []
    if len(tap) != 2:
        return None
    cleanup.adb("shell", "input", "tap", str(tap[0]), str(tap[1]))
    import time as _t

    for _ in range(6):
        _t.sleep(2)
        pkg = cleanup.foreground()
        if pkg and "ninegame" not in pkg and "launcher" not in pkg:
            cleanup.adb("shell", "am", "force-stop", pkg)
            cleanup.adb("shell", "input", "keyevent", "KEYCODE_HOME")
            return pkg
    return None


def known_packages(history: dict) -> dict[str, str]:
    """game name -> package，用于「今天已经装过」的复跑。"""
    out: dict[str, str] = {}
    for run in history.get("runs", []):
        for item in run.get("games", []):
            if isinstance(item, dict) and item.get("name") and item.get("package"):
                out[item["name"]] = item["package"]
    return out


def record_run(history: dict, date: str, games: list[dict], note: str) -> None:
    runs = [r for r in history.get("runs", []) if r.get("date") != date]
    runs.append({"date": date, "games": games, "note": note})
    HISTORY.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=1) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget-min", type=float, default=180.0)
    ap.add_argument("--dry-run", action="store_true", help="只跑到取单+空间核算，不安装不跑测")
    args = ap.parse_args()

    today = dt.date.today().isoformat()
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = OUT_ROOT / f"qa_daily_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    facts: dict = {"date": today, "stamp": stamp, "stages": {}}

    ok, note = runlock.try_acquire("run_daily")
    if not ok:
        print(json.dumps({"ok": False, "code": 3, "reason": note}, ensure_ascii=False))
        return 3

    # 1. 前置条件
    device_ok = connected()
    net_ok, net_note = network_ok() if device_ok else (False, "设备未连接")
    free = free_gb() if device_ok else None
    streak = consecutive_days(dt.date.fromisoformat(today))
    facts["stages"]["preflight"] = {
        "device": device_ok, "network": net_ok, "network_note": net_note,
        "free_gb": free, "streak": streak,
    }
    if not device_ok or not net_ok:
        print(json.dumps({"ok": False, "code": 2, "stage": "preflight", "facts": facts}, ensure_ascii=False))
        return 2
    if streak + 1 >= 4:
        facts["stages"]["preflight"]["blocked"] = f"连续第 {streak + 1} 天，达上限 4"
        print(json.dumps({"ok": False, "code": 2, "stage": "preflight", "facts": facts}, ensure_ascii=False))
        return 2

    # 2. 清场
    history = load_history()
    facts["stages"]["quiesce"] = cleanup.quiesce(recent_packages(history))

    # 3. 取当日可下载首发
    listing = sh(str(HERE / "today_launches.py"), "--json", "--runnable", timeout=600)
    try:
        launches = json.loads(listing.stdout or "[]")
    except json.JSONDecodeError:
        launches = []
    facts["stages"]["today_launches"] = {"count": len(launches), "games": [g["name"] for g in launches]}
    if not launches:
        print(json.dumps({"ok": False, "code": 4, "stage": "today_launches", "facts": facts}, ensure_ascii=False))
        return 4

    # 4. 逐款安装（装前算空间，不够就按最近任务倒序卸载旧包）
    installed: list[dict] = []
    known = known_packages(history)
    for game in launches:
        name = game["name"]
        # 已经装过（当天复跑）：直接进跑测，不再走安装
        if "下载" not in game.get("action", ""):
            pkg = known.get(name) or resolve_installed_package(game)
            if pkg and pkg in capacity.installed_packages():
                installed.append({"name": name, "package": pkg, "size_gb": None,
                                  "budget": {"state": "already-installed"}})
                continue
        need = capacity.required_gb(None)  # 体积未知时按 2 GB × 3 估
        budget = capacity.ensure_capacity(game.get("package", ""), need, recent_packages(history))
        if budget["state"] == "blocked":
            facts.setdefault("blocked_installs", []).append(
                {"game": name, "free_gb": budget["free_gb"], "need_gb": budget["need_gb"]}
            )
            continue
        if args.dry_run:
            continue
        res = sh(str(HERE / "install_game.py"), "--name", name, timeout=1800)
        try:
            payload = json.loads(res.stdout.strip().splitlines()[-1])
        except (json.JSONDecodeError, IndexError):
            payload = {"ok": False, "reason": (res.stdout or res.stderr)[-200:]}
        if payload.get("ok"):
            installed.append({"name": name, "package": payload["package"],
                              "size_gb": capacity.package_size_gb(payload["package"]),
                              "budget": budget})
    facts["stages"]["install"] = {"installed": installed}

    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "facts": facts}, ensure_ascii=False, indent=1))
        return 0
    if not installed:
        print(json.dumps({"ok": False, "code": 5, "stage": "install", "facts": facts}, ensure_ascii=False))
        return 5

    # 5. 跑测（BC/D/E 交给 Artemis）
    games_file = out_dir / "games.json"
    games_file.write_text(json.dumps(
        [{"name": g["name"], "package": g["package"], "schedule": ""} for g in installed],
        ensure_ascii=False))
    run = sh(str(HERE / "run_games.py"), "--games", str(games_file),
             "--budget-min", str(args.budget_min), "--out", str(out_dir), timeout=args.budget_min * 60 + 600)
    facts["stages"]["run_games"] = {"rc": run.returncode, "tail": (run.stdout or "")[-600:]}

    # 6. 收尾：force-stop 本轮游戏（不卸载）
    facts["stages"]["teardown"] = cleanup.teardown([g["package"] for g in installed])
    record_run(history, today,
               [{"name": g["name"], "package": g["package"]} for g in installed], f"queue {stamp}")

    (out_dir / "daily_facts.json").write_text(json.dumps(facts, ensure_ascii=False, indent=1))
    print(json.dumps({"ok": True, "out": str(out_dir), "facts": facts["stages"].get("install")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
