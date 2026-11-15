#!/usr/bin/env python3
"""九游新游质检队列 v2（调度层）。

判定口径（2026-11-15 修订）：
- 完成条件：引导遮罩/手指消失 **且** 商店/充值入口可见 **且** 能真正拉起支付面板（截图即返回）。
- 超时：D 阶段 40 分钟仍未满足完成条件 → 记为 TIMEOUT（超时未完成），不再用时间兜底判 PASS。
- 每款记录：游戏名、角色名、总耗时、D 阶段耗时、状态、分阶段指标。

职责边界：只调用 `artemis run`，不做任何点击决策；观察密度保持每阶段首尾各一张截图。
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVICE = "89FX09M9U"
OUT = ROOT / "traces" / "qa_1114_v2"
STATUS = OUT / "queue_status.json"
PATH_ENV = (
    "/Users/zw-mini/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:"
    "/Users/zw-mini/Library/Android/sdk/platform-tools"
)
BASE_ENV = {
    "HOME": os.environ.get("HOME", "/Users/zw-mini"),
    "PATH": PATH_ENV,
    "GEMINI_API_KEY": "DISABLED-NO-GEMINI",
    "GOOGLE_API_KEY": "DISABLED-NO-GEMINI",
    "ARTEMIS_PRESET": "ds-qwen-hybrid",
    "ADB_DEVICE_SERIAL": DEVICE,
}

GAMES = {
    "dasheng": {"name": "大圣", "slot": "11-12 11:30 首发", "pkg": "com.qjyx.android.ds.aligames"},
    "yidiansanguo": {"name": "一点三国", "slot": "11-12 10:00 首发", "pkg": "com.gzhh.ydsg.aligames"},
    "yijianduannian": {"name": "一剑断念", "slot": "11-13 09:00 首发", "pkg": "com.qy.yjdn1.aligames"},
    "doupo": {"name": "斗破苍穹：异火降世", "slot": "11-13 10:00 首发", "pkg": "com.rastar.dpcqyhjs.aligames"},
    "chongba": {"name": "冲吧勇者", "slot": "11-13 08:00 计费删档内测", "pkg": "com.yxa.sgwgcbyzyh.aligames"},
}

RULES = (
    "你是 Android 手游质检员，只汇报亲眼在屏幕上确认的事实。规则："
    "1. 遇到手机号/验证码/实名/人脸验证，立即停止并汇报 BLOCKED，不要绕过。"
    "2. 严禁点击任何最终付款/确认支付，严禁输入支付密码。充值/支付面板只要成功拉起并看到商品或金额，"
    "立即截图，然后按返回退出，不要继续。"
    "3. 出现明确失败提示（链接已失效、版本过旧、网络错误、维护、闪退）即视为确定结果，立即汇报，"
    "严禁反复重启应用、清理缓存或重复试探。"
    "4. 游戏画面没有 UI 树时用视觉定位，每次点击后必须看新截图确认画面变化。"
    "5. 若连续 8 次操作画面无任何变化，判定为卡死，汇报 result=FAIL。"
    "6. 启动应用时**必须**使用包名（package name），严禁使用中文应用名，否则应用名解析会失败并卡住。"
)


def adb(*args: str, timeout: int = 40) -> str:
    try:
        return subprocess.run(
            ["adb", "-s", DEVICE, *args], capture_output=True, text=True,
            env=BASE_ENV, timeout=timeout,
        ).stdout
    except Exception as exc:  # noqa: BLE001
        return f"<adb error: {exc}>"


def shot(path: Path) -> None:
    try:
        with open(path, "wb") as fh:
            subprocess.run(
                ["adb", "-s", DEVICE, "exec-out", "screencap", "-p"],
                stdout=fh, env=BASE_ENV, timeout=30, check=False,
            )
    except Exception:  # noqa: BLE001
        pass


def reset_device(exclude: str | None = None) -> str:
    """Force-stop every test game, go home, return the foreground window title."""
    for g in GAMES.values():
        if g["pkg"] != exclude:
            adb("shell", "am", "force-stop", g["pkg"])
    adb("shell", "input", "keyevent", "KEYCODE_HOME")
    time.sleep(2.5)
    out = adb("shell", "dumpsys window | grep mCurrentFocus")
    return out.strip().split("u0 ")[-1][:80]


def pkgs() -> set[str]:
    out = adb("shell", "pm", "list", "packages")
    return {ln.split(":", 1)[1].strip() for ln in out.splitlines() if ln.startswith("package:")}


def kill_tree(proc: subprocess.Popen) -> None:
    import signal

    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def clean_log(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def run_phase(
    slug: str, phase: str, goal: str, timeout_s: int, lock_package: str | None = None
) -> dict:
    gdir = OUT / slug
    (gdir / "shots").mkdir(parents=True, exist_ok=True)
    log = gdir / f"run_{phase}.log"
    fg = reset_device()
    print(f"  [reset] {phase} 前前台: {fg}", flush=True)
    shot(gdir / "shots" / f"{phase}_start.png")
    adb("logcat", "-c")
    t0 = time.time()
    timed_out = False
    with open(log, "w") as fh:
        proc = subprocess.Popen(
            ["uv", "run", "python", "-m", "artemis.main", "run", goal,
             "--profile", "flash", "--device-serial", DEVICE,
             "--test-name", f"qa1115_{slug}_{phase}", "--standalone"]
            + (["--locked-app", lock_package] if lock_package else []),
            cwd=str(ROOT), env=BASE_ENV, stdout=fh, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        stall_s = 300
        deadline = time.time() + timeout_s
        last_size, last_growth = -1, time.time()
        while proc.poll() is None:
            time.sleep(10)
            size = log.stat().st_size if log.exists() else 0
            if size != last_size:
                last_size, last_growth = size, time.time()
            elif time.time() - last_growth > stall_s:
                timed_out = True
                print(f"  [watchdog] {phase} 日志 {stall_s}s 无增长，终止", flush=True)
                kill_tree(proc)
                break
            if time.time() > deadline:
                timed_out = True
                print(f"  [watchdog] {phase} 超出 {timeout_s}s，终止", flush=True)
                kill_tree(proc)
                break
        rc = proc.wait()
        kill_tree(proc)

    wall = round(time.time() - t0, 1)
    shot(gdir / "shots" / f"{phase}_end.png")
    (gdir / f"logcat_{phase}.txt").write_text(adb("logcat", "-d", "-v", "time", timeout=90) or "", encoding="utf-8")
    body = clean_log(log.read_text(errors="ignore")) if log.exists() else ""
    (gdir / f"crash_{phase}.txt").write_text(adb("logcat", "-b", "crash", "-d") or "", encoding="utf-8")
    report = ""
    m = re.search(r"report_task_status\(\{(.*?)\}\)", body, re.S)
    if m:
        report = m.group(1)[:2500]
    return {
        "phase": phase, "wall_s": wall, "returncode": rc, "timed_out": timed_out,
        "turns": len(re.findall(r"Flash Turn \d+", body)),
        "clicks": body.count("[ADB] input tap"),
        "deepseek_calls": body.count("api.deepseek.com"),
        "siliconflow_calls": body.count("api.siliconflow.cn"),
        "google_calls": len(re.findall(r"generativelanguage|googleapis\.com/v1", body)),
        "reported": report, "body_len": len(body),
    }


def verdict_of(phase: dict, timeout_s: int) -> str:
    """Only trust structured signals (result= token and status field), never prose."""
    rep = phase.get("reported") or ""
    if phase.get("timed_out"):
        return "TIMEOUT"
    low = rep.lower()
    m = re.search(r"result\s*[=:：]\s*[\"'\s]*(pass|fail|blocked|timeout)", low)
    if m:
        return {"pass": "PASS", "fail": "FAIL", "blocked": "BLOCKED", "timeout": "TIMEOUT"}[m.group(1)]
    m = re.search(r"[\"']?status[\"']?\s*:\s*[\"']?(completed|failed|timeout|error)", low)
    if m:
        return {"completed": "PASS", "failed": "FAIL",
                "timeout": "TIMEOUT", "error": "FAIL"}[m.group(1)]
    if "blocked" in low:
        return "BLOCKED"
    return "UNKNOWN"


def e_phase_verdict(phase: dict, timeout_s: int) -> str:
    """E-stage verdict: an unparseable report is INCONCLUSIVE, never PASS."""
    v = verdict_of(phase, timeout_s)
    return "INCONCLUSIVE" if v == "UNKNOWN" else v


def extract_character(report: str) -> str:
    for pat in (
        r"角色名\s*[:：]\s*[『「\"]?([^\s，,。；;\\『』「」\"]+)",
        r"角色名\s*[『「\"]([^』」\"]+)",
        r"玩家\s*[『「\"]([^』」\"]+)",
        r"角色\s*[『「\"]([^』」\"]+)",
    ):
        m = re.search(pat, report or "")
        if m:
            return m.group(1).strip()
    return ""


def save_status(state: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def write_summary(state: dict) -> None:
    rows = []
    for slug, g in state["games"].items():
        rows.append({
            "游戏": g["name"],
            "档期": g["slot"],
            "角色": g.get("character") or "-",
            "状态": g.get("verdict") or "-",
            "总耗时(s)": g.get("total_wall") or "-",
            "D耗时(s)": g.get("d_wall") or "-",
            "阶段明细": " / ".join(
                f"{p['phase']}:{p['wall_s']:.0f}s{'(timeout)' if p['timed_out'] else ''}"
                for p in g.get("phases", [])
            ),
            "说明": (g.get("note") or "")[:60],
        })
    md = ["# 九游新游质检 v2 — 汇总（2026-11-15）", "",
          "完成条件：引导消失 + 商店/支付入口可见 + 支付面板可拉起；D 阶段 40 分钟未满足记 TIMEOUT。", "",
          "| 游戏 | 档期 | 角色 | 状态 | 总耗时(s) | D耗时(s) | 阶段明细 |",
          "|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['游戏']} | {r['档期']} | {r['角色']} | {r['状态']} | {r['总耗时(s)']} | {r['D耗时(s)']} | {r['阶段明细']} |")
    (OUT / "SUMMARY.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    with open(OUT / "summary.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            w.writeheader()
            w.writerows(rows)


def main() -> int:
    wanted = sys.argv[1].split(",") if len(sys.argv) > 1 else list(GAMES)
    state: dict = {"started_at": datetime.now().isoformat(timespec="seconds"),
                   "finished_at": None, "games": {}}
    installed = pkgs()
    for slug in wanted:
        meta = GAMES[slug]
        name, pkg = meta["name"], meta["pkg"]
        g = state["games"].setdefault(slug, {
            "name": name, "slot": meta["slot"], "pkg": pkg,
            "phases": [], "character": "", "verdict": "RUNNING",
        })
        save_status(state)
        print(f"\n=== [{name}] {datetime.now():%H:%M:%S} ===", flush=True)
        game_t0 = time.time()

        adb("shell", "am", "force-stop", pkg)
        if pkg not in installed:
            g["verdict"] = "BLOCKED_INSTALL"
            g["note"] = "包未安装且未启用阶段A下载"
            print(f"[{name}] 未安装，跳过", flush=True)
            continue

        # B+C 启动与登录
        bc = run_phase(slug, "BC", (
            RULES
            + f"任务（阶段B+C 启动与登录）：打开游戏《{name}》（包名 {pkg}）。"
            + "同意必要的用户协议与权限弹窗，等待资源更新与SDK初始化完成（进度条走完）。"
            + "登录优先选「九游账号」或「一键登录」；若只能手机号验证码登录则汇报 BLOCKED。"
            + "若出现「链接已失效」「登录失败」「维护」等确定性失败提示，直接汇报不要重试。"
            + "到达角色创建或游戏内场景后，report_task_status 汇报 stage=B+C、result=PASS/FAIL/BLOCKED、"
            + "并用「角色名：<你看到的角色名，若无则写 未创建>」写明角色。"
        ), 900, lock_package=pkg)
        g["phases"].append(bc)
        save_status(state)
        if verdict_of(bc, 900) in ("BLOCKED", "FAIL", "TIMEOUT"):
            g["verdict"] = verdict_of(bc, 900)
            g["note"] = "B+C 未通过"
            g["total_wall"] = round(time.time() - game_t0, 1)
            save_status(state)
            print(f"[{name}] B+C {g['verdict']}，跳过后续", flush=True)
            continue

        # D 新手引导 + 支付面板（核心判据，40 分钟）
        d_timeout = 2400
        d = run_phase(slug, "D", (
            RULES
            + f"任务（阶段D 新手引导与支付验证）在《{name}》（包名 {pkg}，启动时用包名）里按引导提示逐步操作：点击高亮区域、"
            + "跳过剧情对话、选择默认角色或推荐选项，直到引导遮罩与引导手指完全消失。"
            + "然后完成三项验收，缺一不可："
            + "① 引导遮罩与手指消失（连续等待两次 4 秒后确认不回弹）；"
            + "② 主界面可见商店或充值入口（按钮、横幅、或资源旁的「+」均可）；"
            + "③ 实际点开该商店/充值入口，确认支付或充值面板成功弹出（看到商品、金额或档位即可），"
            + "截图后立即按返回退出，严禁点击任何付款或确认支付。"
            + "三项全部满足 → result=PASS。"
            + "若累计游玩达到 40 分钟仍未能满足上述三项，立即 result=TIMEOUT（超时未完成），不要继续尝试。"
            + "report_task_status 汇报 stage=D、result、三项验收各自的证据，"
            + "并写明「角色名：<角色名>」。"
        ), d_timeout, lock_package=pkg)
        g["phases"].append(d)
        g["d_wall"] = d["wall_s"]
        g["character"] = extract_character(d["reported"]) or g.get("character", "")
        save_status(state)

        d_verdict = verdict_of(d, d_timeout)
        if d_verdict != "PASS":
            g["verdict"] = "TIMEOUT" if (d["timed_out"] or d_verdict == "TIMEOUT") else d_verdict
            g["note"] = f"D 阶段 {g['verdict']}"
            g["total_wall"] = round(time.time() - game_t0, 1)
            save_status(state)
            print(f"[{name}] D {g['verdict']}", flush=True)
            continue

        # E 主界面巡检
        e = run_phase(slug, "E", (
            RULES
            + f"任务（阶段E 主界面巡检）在《{name}》（包名 {pkg}）主界面：列出所有可点击功能按钮（背包、角色、活动、"
            + "邮件、商城、充值、设置等），逐个点击，确认页面有变化且加载正常，再关闭或返回主界面，再点下一个。"
            + "其中商店/充值入口必须再次打开并截图。"
            + "最终给出逐按钮结果表（按钮名 / 是否有反应 / 页面是否正常）。"
            + "report_task_status 汇报 stage=E、result、逐按钮表。"
        ), 1200, lock_package=pkg)
        g["phases"].append(e)
        g["total_wall"] = round(time.time() - game_t0, 1)
        g["verdict"] = e_phase_verdict(e, 1200)
        all_body = clean_log((OUT / slug / "run_BC.log").read_text(errors="ignore"))
        if not g["character"]:
            g["character"] = extract_character(all_body)
        save_status(state)
        print(f"[{name}] 完成 verdict={g['verdict']}", flush=True)

    state["finished_at"] = datetime.now().isoformat(timespec="seconds")
    save_status(state)
    write_summary(state)
    print("\nALL_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
