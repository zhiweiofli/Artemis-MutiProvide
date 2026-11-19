#!/usr/bin/env python3
"""对给定的首发游戏清单跑 B+C / D / E 三阶段质检，并输出对比用汇总。

用法：
    python3 scripts/qa_daily/run_games.py --games games.json \
        [--budget-min 150] [--out traces/qa_daily_YYYY-MM-DD]

games.json：[{"name": "…", "package": "…", "schedule": "10:00 首发"}, …]
D 阶段开启 A1 结构化验收硬门（ARTEMIS_FLASH_REPORT_CHECKS=1）并传 --locked-app（C3）。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.util
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "qa_daily"))

_spec = importlib.util.spec_from_file_location("qa_queue", ROOT / "scripts" / "qa_1114_queue.py")
q = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(q)

BC_TIMEOUT, D_TIMEOUT, E_TIMEOUT = 900, 1500, 1200


def installed(package: str) -> bool:
    out = subprocess.run(
        ["adb", "-s", q.DEVICE, "shell", "pm", "list", "packages", package],
        capture_output=True, text=True, timeout=30,
    ).stdout
    return package in out


def goal_bc(name: str, package: str) -> str:
    return (
        q.RULES
        + f"任务（阶段B+C 启动与登录）：打开游戏《{name}》（包名 {package}）。"
        + "同意必要的用户协议与权限弹窗，等待资源更新与SDK初始化完成（进度条走完）。"
        + "登录优先选「九游账号」或「一键登录」；若只能手机号验证码登录则汇报 result=BLOCKED。"
        + "到达角色创建或游戏内场景后 report_task_status，explanation 第一行必须原样写出 result=PASS 或 result=FAIL 或 result=BLOCKED（三选一，照字面写英文 result=），再用「角色名：…」写明角色。"
        + "并用「角色名：<角色名，若无则写 未创建>」写明角色。"
    )


def goal_d(name: str, package: str) -> str:
    return (
        q.RULES
        + f"任务（阶段D 新手引导与支付验证）在《{name}》（包名 {package}）里按引导提示逐步操作："
        + "点击高亮区域、跳过剧情对话、选择默认或推荐选项，直到引导遮罩与引导手指消失。"
        + "然后完成三项验收：① 引导遮罩与手指消失（连续等待两次 4 秒确认不回弹）；"
        + "② 主界面可见商店或充值入口；③ 实际点开该入口，确认支付或充值面板弹出（看到商品、金额或档位即可），"
        + "截图后立即返回，严禁点击任何付款或确认支付。"
        + "report_task_status 的 explanation 第一行必须原样写出 result=PASS 或 result=FAIL 或 result=BLOCKED（三选一，照字面写英文 result=），并逐项回答 check_guide_gone / check_entry_visible / check_panel_opened（YES/NO），"
        + "并在 evidence 里为每项写明截图名或画面原文；三项全 YES 才能 status=completed。"
    )


def goal_e(name: str, package: str) -> str:
    return (
        q.RULES
        + f"任务（阶段E 主界面巡检）在《{name}》（包名 {package}）主界面：列出所有可点击功能按钮"
        + "（背包、角色、活动、邮件、商城、充值、设置等），逐个点击，确认页面有变化且加载正常，"
        + "再关闭或返回主界面，再点下一个。商店/充值入口必须再次打开并截图。"
        + "最终给出逐按钮结果表（按钮名 / 是否有反应 / 页面是否正常）。"
        + "report_task_status 的 explanation 第一行必须原样写出 result=PASS 或 result=FAIL 或 result=BLOCKED（三选一，照字面写英文 result=），再给逐按钮表。"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--games", required=True)
    ap.add_argument("--budget-min", type=float, default=150.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    games = json.loads(Path(args.games).read_text())
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    out = Path(args.out or (ROOT / "traces" / f"qa_daily_{stamp}"))
    out.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + args.budget_min * 60

    results = []
    for game in games:
        name, package = game["name"], game["package"]
        slug = game.get("slug") or f"qa_{abs(hash(package)) % 10**8}"
        row = {"name": name, "package": package, "schedule": game.get("schedule", ""),
               "verdict": "SKIPPED", "note": "", "total_wall": 0.0, "d_wall": 0.0, "character": ""}
        if time.time() > deadline:
            row["note"] = "时间预算用尽"
            results.append(row)
            continue
        if not installed(package):
            row["note"] = "未安装"
            results.append(row)
            continue

        t0 = time.time()
        bc = q.run_phase(slug, "BC", goal_bc(name, package), BC_TIMEOUT, lock_package=package)
        bc_verdict = q.verdict_of(bc, BC_TIMEOUT)
        if bc_verdict != "PASS":
            row.update(verdict="BLOCKED" if bc_verdict == "BLOCKED" else "FAIL",
                       note=f"B+C {bc_verdict}", total_wall=round(time.time() - t0, 1))
            results.append(row)
            continue

        d = q.run_phase(slug, "D", goal_d(name, package), D_TIMEOUT,
                        lock_package=package, extra_env={"ARTEMIS_FLASH_REPORT_CHECKS": "1"})
        d_verdict = q.verdict_of(d, D_TIMEOUT)
        row["d_wall"] = round(d.get("wall_s") or 0, 1)
        row["character"] = q.extract_character(d.get("reported", "")) or ""
        if d_verdict == "UNKNOWN":
            d_verdict = "INCONCLUSIVE"

        e = q.run_phase(slug, "E", goal_e(name, package), E_TIMEOUT, lock_package=package)
        e_verdict = q.e_phase_verdict(e, E_TIMEOUT)

        if d_verdict != "PASS":
            verdict = "TIMEOUT" if (d.get("timed_out") or d_verdict == "TIMEOUT") else d_verdict
            note = f"D {d_verdict}；E 未作为判据"
        else:
            verdict, note = e_verdict, "D 通过"
        row.update(verdict=verdict, note=note, total_wall=round(time.time() - t0, 1))
        results.append(row)
        (out / "games_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))

    (out / "games_result.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    with open(out / "summary.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(results[0]) if results else ["name"])
        w.writeheader()
        w.writerows(results)

    lines = [f"# 每日质检结果 {stamp}", "", "| 游戏 | 档期 | 判决 | 总耗时(s) | D(s) | 角色 | 说明 |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['name']} | {r['schedule']} | {r['verdict']} | {r['total_wall']} |"
                     f" {r['d_wall']} | {r['character']} | {r['note']} |")
    if len(games) < 5:
        lines.append("")
        lines.append(f"> 当日可下载首发仅 {len(games)} 款（不足 5 款），已跑完全部可跑项。")
    (out / "SUMMARY.md").write_text("\n".join(lines) + "\n")

    ledger = ROOT / "docs" / "qa_daily" / "ledger.json"
    data = json.loads(ledger.read_text())
    today = dt.date.today().isoformat()
    verdicts = sum(1 for r in results if r["verdict"] == "PASS")
    data["runs"] = [r for r in data["runs"] if r.get("date") != today]
    data["runs"].append({
        "date": today,
        "rounds": 1,
        "games": len(results),
        "verdict": f"{verdicts} PASS / {len(results) - verdicts} 非 PASS",
        "launches_available": len(games),
        "notes": f"每日队列 {stamp}",
    })
    ledger.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    print(json.dumps({"out": str(out), "verdicts": {r["name"]: r["verdict"] for r in results}},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
