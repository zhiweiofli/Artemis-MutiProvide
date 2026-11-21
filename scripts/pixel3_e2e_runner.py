#!/usr/bin/env python3
"""Live Android Pixel 3 paired E2E benchmark runner for ARTEMIS.

Executes real FlashRunner tasks on the connected Pixel 3 (89FX09M9U) under both
baseline (`gemini-baseline`) and target (`ds-qwen-hybrid`) presets, extracts
verifiable metrics directly from `traces/data_engine.db`, and satisfies the
budget contract required by `scripts/run_benchmark_comparison.py --mode e2e`.
"""

import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time
from typing import Any
import uuid

REPO_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = REPO_ROOT / "traces/data_engine.db"
DEVICE_SERIAL = os.environ.get("ADB_DEVICE_SERIAL", "89FX09M9U")
GOAL = "Open Settings and check Battery level"

# Pricing rates aligned with PRICING_TABLE_V1 (USD per 1M tokens)
MODEL_RATES = {
    "google": {"input": 1.25, "cached": 0.3125, "output": 5.00},
    "deepseek": {"input": 0.14, "cached": 0.014, "output": 0.28},
    "qwen": {"input": 0.40, "cached": 0.10, "output": 1.20},
}


def _clean_env(preset: str) -> dict[str, str]:
    """Construct minimal deterministic env matching verified shell environment."""
    home = os.environ.get("HOME", str(Path.home()))
    env = {
        "HOME": home,
        "PATH": "/Users/zw-mini/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/Users/zw-mini/Library/Android/sdk/platform-tools",
        "ARTEMIS_PRESET": preset,
        "ADB_DEVICE_SERIAL": DEVICE_SERIAL,
    }
    # Propagate proxy/locale if present so TLS requests work properly
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "http_proxy",
        "https_proxy",
        "LANG",
        "LC_ALL",
    ):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _reset_device_home() -> None:
    """Return Pixel 3 to home screen before each run."""
    env = _clean_env("ds-qwen-hybrid")
    subprocess.run(
        ["adb", "-s", DEVICE_SERIAL, "shell", "input", "keyevent", "KEYCODE_HOME"],
        env=env,
        capture_output=True,
        timeout=10,
        check=False,
    )
    time.sleep(1.5)


def _extract_session_metrics(session_id: str, preset: str, wall_ms: float) -> dict[str, Any]:
    """Read authentic execution telemetry from traces/data_engine.db for session_id."""
    if not DB_PATH.exists():
        raise RuntimeError(f"DataEngine DB not found at {DB_PATH}")

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    try:
        cur.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        sess_row = cur.fetchone()
        if not sess_row:
            return {
                "success": False,
                "latency_ms": round(wall_ms, 2),
                "cost_usd": 0.0,
                "grounding_correct": False,
                "recovery_rate": 0.0,
                "video_accuracy": 0.0,
                "error": f"Session {session_id} missing from DB",
            }

        sess = dict(sess_row)
        success = sess.get("status") == "completed"

        # Step count & visual summary coverage
        cur.execute("SELECT * FROM steps WHERE session_id = ?", (session_id,))
        steps = [dict(r) for r in cur.fetchall()]
        num_steps = max(1, len(steps))
        step_latency_ms = round(wall_ms / num_steps, 2)

        # Video & visual step consistency
        video_path = sess.get("video_filepath")
        has_video = bool(
            video_path and Path(video_path).exists() and Path(video_path).stat().st_size > 0
        )
        summarized_steps = sum(1 for s in steps if s.get("summary"))
        # Visual action steps are steps before final report (num_steps - 1)
        action_steps = max(1, num_steps - 1)
        if has_video and success:
            video_accuracy = round(min(1.0, summarized_steps / action_steps), 4)
        else:
            video_accuracy = 0.0

        # Token usage & real cost calculation
        cur.execute(
            "SELECT payload FROM traces WHERE session_id = ? AND type = 'llm_call' AND name = 'llm_usage'",
            (session_id,),
        )
        usage_rows = cur.fetchall()
        total_cost = 0.0
        total_prompt = 0
        total_cached = 0
        total_completion = 0

        for r in usage_rows:
            p = json.loads(r["payload"]) if r["payload"] else {}
            p_tok = int(p.get("prompt_tokens") or 0)
            c_tok = int(p.get("completion_tokens") or 0)
            cached_tok = int(p.get("cached_tokens") or 0)
            uncached_tok = max(0, p_tok - cached_tok)
            total_prompt += p_tok
            total_cached += cached_tok
            total_completion += c_tok

            src = str(p.get("source") or "").lower()
            if "deepseek" in src:
                rate = MODEL_RATES["deepseek"]
            elif "qwen" in src:
                rate = MODEL_RATES["qwen"]
            else:
                rate = MODEL_RATES["google"]

            call_cost = (
                (uncached_tok / 1_000_000.0) * rate["input"]
                + (cached_tok / 1_000_000.0) * rate["cached"]
                + (c_tok / 1_000_000.0) * rate["output"]
            )
            total_cost += call_cost

        # Grounding / action execution correctness
        cur.execute(
            "SELECT status FROM traces WHERE session_id = ? AND type = 'action'",
            (session_id,),
        )
        action_rows = cur.fetchall()
        action_ok_count = sum(1 for a in action_rows if a["status"] == "success")
        grounding_correct = bool(
            success and len(action_rows) > 0 and action_ok_count == len(action_rows)
        )

        # Recovery & fault resilience
        cur.execute("SELECT count(*) FROM failed_outputs WHERE session_id = ?", (session_id,))
        failed_out_cnt = int(cur.fetchone()[0] or 0)
        if not success:
            recovery_rate = 0.0
        elif failed_out_cnt == 0:
            recovery_rate = 1.0
        else:
            # Succeeded despite intermediate failures -> recovered
            recovery_rate = 1.0

        return {
            "success": success,
            "latency_ms": step_latency_ms,
            "wall_ms": round(wall_ms, 2),
            "request_bytes": total_prompt * 4,
            "cost_usd": round(total_cost, 6),
            "prompt_tokens": total_prompt,
            "cached_tokens": total_cached,
            "completion_tokens": total_completion,
            "grounding_correct": grounding_correct,
            "recovery_rate": recovery_rate,
            "video_accuracy": video_accuracy,
            "session_id": session_id,
            "preset": preset,
        }
    finally:
        conn.close()


def _execute_single_preset(run_idx: int, preset: str) -> dict[str, Any]:
    """Execute one FlashRunner task on Pixel 3 under the specified preset."""
    _reset_device_home()
    session_id = str(uuid.uuid4())
    test_name = f"p4_e2e_r{run_idx}_{preset.replace('-', '_')}"
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "artemis.main",
        "run",
        GOAL,
        "--profile",
        "flash",
        "--device-serial",
        DEVICE_SERIAL,
        "--session-id",
        session_id,
        "--test-name",
        test_name,
        "--standalone",
    ]
    t0 = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=_clean_env(preset),
        capture_output=True,
        text=True,
        timeout=180,
    )
    wall_ms = (time.time() - t0) * 1000.0
    metrics = _extract_session_metrics(session_id, preset, wall_ms)
    if proc.returncode != 0:
        metrics["success"] = False
        metrics["cli_returncode"] = proc.returncode
    return metrics


def run_pixel3_benchmark_iteration(
    run_idx: int,
    baseline_preset: str,
    target_preset: str,
    remaining_budget_usd: float,
) -> dict[str, Any]:
    """Paired Pixel 3 benchmark runner satisfying run_benchmark_comparison budget contract."""
    if remaining_budget_usd < 0.08:
        raise RuntimeError(
            f"Insufficient remaining budget ${remaining_budget_usd:.4f} for paired Pixel 3 run"
        )

    base_metrics = _execute_single_preset(run_idx, baseline_preset)
    tgt_metrics = _execute_single_preset(run_idx, target_preset)
    _reset_device_home()

    total_run_cost = round(base_metrics["cost_usd"] + tgt_metrics["cost_usd"], 6)
    overall_ok = bool(base_metrics["success"] and tgt_metrics["success"])

    return {
        "success": overall_ok,
        "cost_usd": total_run_cost,
        "source": "pixel3_native_flash_runner_e2e",
        "baseline": base_metrics,
        "target": tgt_metrics,
    }


run_pixel3_benchmark_iteration.max_cost_per_run_usd = 0.15
