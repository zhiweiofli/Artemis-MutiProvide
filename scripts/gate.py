#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Machine-Verifiable Gate and Task Board Auto-Synchronization Script.

Enforces L1-L4 gates and automatically synchronizes docs/TASK_BOARD.md
and Archify visual explainer board (.archify/.../candidate.archify.md + HTML).

Usage:
    uv run python scripts/gate.py --level L4 --phase P2-GREEN --json
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent

TARGET_TESTS = [
    "tests/unit/test_llm_gateway.py",
    "tests/unit/test_llm_reliability.py",
    "tests/unit/test_llm_structured.py",
    "tests/unit/test_preset_switching.py",
    "tests/unit/test_deepseek_qwen_providers.py",
    "tests/unit/test_object_detector_coords.py",
]

REQUIRED_SKILLS = [
    "workbench-project",
    "matt-tdd",
    "matt-codebase-design",
    "matt-diagnosing-bugs",
    "matt-code-review",
    "archify",
]


def check_l1_project_entry() -> dict[str, Any]:
    """L1: Verify project entrance via check.mjs doctor."""
    doctor_script = REPO_ROOT / ".agents/skills/workbench-project/scripts/check.mjs"
    if not doctor_script.exists():
        return {
            "level": "L1",
            "passed": False,
            "error": f"Doctor script missing: {doctor_script}",
        }

    try:
        proc = subprocess.run(
            ["node", str(doctor_script), "doctor", "."],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return {
                "level": "L1",
                "passed": False,
                "error": f"doctor command exited with {proc.returncode}: {proc.stderr}",
            }
        data = json.loads(proc.stdout)
        status = data.get("status")
        return {
            "level": "L1",
            "passed": status == "healthy",
            "status": status,
            "checks": data.get("checks", []),
        }
    except Exception as e:
        return {"level": "L1", "passed": False, "error": str(e)}


def check_l2_skills_installed() -> dict[str, Any]:
    """L2: Verify all 6 atomic skills directories exist and have SKILL.md."""
    skills_dir = REPO_ROOT / ".agents/skills"
    missing = []
    for skill in REQUIRED_SKILLS:
        skill_file = skills_dir / skill / "SKILL.md"
        if not skill_file.exists():
            missing.append(skill)
    return {
        "level": "L2",
        "passed": len(missing) == 0,
        "skills_checked": REQUIRED_SKILLS,
        "missing_skills": missing,
    }


def check_l3_dependencies_and_baseline() -> dict[str, Any]:
    """L3: Verify runtime environment, dependencies, and protected baseline files."""
    errors = []

    # 1. Python version >= 3.12
    py_ver = sys.version_info
    if py_ver < (3, 12):
        errors.append(f"Python 3.12+ required, got {py_ver.major}.{py_ver.minor}")

    # 2. Dependency imports
    try:
        import langchain_core
        import langchain_openai
        import pydantic
    except ImportError as e:
        errors.append(f"Missing dependency: {e}")

    # 3. Check baseline protection (ensure unauthorized files are not tampered)
    baseline_path = REPO_ROOT / ".agent/baseline.json"
    if baseline_path.exists():
        try:
            with open(baseline_path, encoding="utf-8") as f:
                baseline_data = json.load(f)
            files = baseline_data.get("files", {})
            p2_authorized = {
                "artemis/config/constants.py",
                "artemis/config/settings.py",
                "artemis/config/llm.py",
                "third_party/mobile_use/config/llm.py",
                "config/artemis.jsonc",
                "artemis/llm/router.py",
                "artemis/llm/reliability.py",
                "artemis/llm/google/usage.py",
                "artemis/services/llm.py",
                "artemis/memory/chunking.py",
                "artemis/agents/flash/summarizer.py",
                "artemis/agents/flash/runner.py",
                "artemis/agents/explorer/explorer.py",
                "artemis/agents/object_detector/object_detector.py",
                "artemis/agents/object_detector/object_detector.json",
                "scripts/gate.py",
                "scripts/probe_capabilities.py",
                "scripts/run_benchmark_comparison.py",
            }
            for rel_path, val in files.items():
                if rel_path in p2_authorized:
                    continue
                expected_sha = (
                    val
                    if isinstance(val, str)
                    else (val.get("sha256") if isinstance(val, dict) else None)
                )
                p = REPO_ROOT / rel_path
                if not p.exists():
                    errors.append(f"Protected baseline file missing: {rel_path}")
                else:
                    actual_sha = hashlib.sha256(p.read_bytes()).hexdigest()
                    if expected_sha and actual_sha != expected_sha:
                        errors.append(f"Unauthorized baseline file modified: {rel_path}")
        except Exception as e:
            errors.append(f"Error reading baseline: {e}")

    return {
        "level": "L3",
        "passed": len(errors) == 0,
        "python_version": f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}",
        "errors": errors,
    }


def check_l4_unit_tests(phase: str) -> dict[str, Any]:
    """L4: Run test suite according to phase expectations."""
    cmd = ["uv", "run", "pytest"] + TARGET_TESTS + ["-q"]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    stdout = proc.stdout
    stderr = proc.stderr

    if phase == "P1-RED":
        # Expect 25 passed, 12 failed
        passed = proc.returncode != 0 and "25 passed" in stdout and "12 failed" in stdout
    else:  # P2-GREEN, P3-REVIEW, P4-BENCH
        # Expect 37 passed, returncode 0
        passed = proc.returncode == 0 and "37 passed" in stdout

    return {
        "level": "L4",
        "phase": phase,
        "passed": passed,
        "exit_code": proc.returncode,
        "summary": stdout.strip().splitlines()[-1] if stdout.strip() else "",
        "raw_stdout": stdout,
        "raw_stderr": stderr,
    }


def sync_task_board(phase: str, report_or_passed: Any) -> dict[str, Any]:
    """Sync docs/TASK_BOARD.md and compile Archify explainer board."""
    sync_results = {}

    if isinstance(report_or_passed, dict):
        l4_passed = report_or_passed.get("gates", {}).get("L4", {}).get("passed", False)
    else:
        l4_passed = bool(report_or_passed)

    # 1. Update docs/TASK_BOARD.md only if L4 passed for P2-GREEN
    task_board_file = REPO_ROOT / "docs/TASK_BOARD.md"
    if task_board_file.exists() and l4_passed and phase == "P2-GREEN":
        content = task_board_file.read_text(encoding="utf-8")
        # Update P2-GREEN status from READY, REWORK, or IN_PROGRESS to DONE
        content = re.sub(
            r"(\|\s*\*\*`P2-GREEN`\*\*.*?)(\|\s*`(?:READY|REWORK|IN_PROGRESS)`\s*\|)",
            r"\1| `DONE` |",
            content,
        )
        # Update P3-REVIEW status from BLOCKED or WAITING_P2_REWORK to READY
        content = re.sub(
            r"(\|\s*\*\*`P3-REVIEW`\*\*.*?)(\|\s*`(?:BLOCKED|WAITING_P2_REWORK)`\s*\|)",
            r"\1| `READY` |",
            content,
        )
        # Update B1-B7 code resolution status to RESOLVED and test status to GREEN
        content = content.replace("`FROZEN_RED` | `SPEC_FROZEN`", "`GREEN` | `RESOLVED`")
        # Update L4 status in L1-L5 table
        content = re.sub(
            r"(\|\s*\*\*L4 真实任务已完成\*\*.*?\|\s*)`(?:IN_PROGRESS|FAIL_REVIEW|PARTIAL)`(\s*\|)",
            r"\1`PASS`\2",
            content,
        )
        task_board_file.write_text(content, encoding="utf-8")
        sync_results["task_board_updated"] = True

    # 2. Update .archify candidate markdown
    archify_dir = REPO_ROOT / ".archify/explainer-phase-task-board-20261109-141300"
    candidate_file = archify_dir / "candidate.archify.md"
    html_file = archify_dir / "phase-task-board.html"

    if candidate_file.exists() and l4_passed and phase == "P2-GREEN":
        c_content = candidate_file.read_text(encoding="utf-8")
        # Update intro text to reflect P2-GREEN passing and waiting for P3
        c_content = re.sub(
            r"首次 P3 审查为 \*\*REWORK\*\*.*?当前返工，P3 待复审。",
            "P2 返工完成并通过 L4 全量门禁（37 passed），等待 P3 双轴独立复审。",
            c_content,
        )
        # Update phase status table
        c_content = re.sub(
            r"(\|\s*`P2-GREEN`\s*\|.*?\|\s*)\{[^}]+\}(\s*\|)",
            r"\1{good:DONE}\2",
            c_content,
        )
        c_content = re.sub(
            r"(\|\s*`P3-REVIEW`\s*\|.*?\|\s*)(?:BLOCKED|\{[^}]+\})(\s*\|)",
            r"\1{caution:READY}\2",
            c_content,
        )
        c_content = re.sub(
            r"(\|\s*`P4-BENCH`\s*\|.*?\|\s*)(?:BLOCKED|\{[^}]+\})(\s*\|)",
            r"\1BLOCKED\2",
            c_content,
        )
        # Update blocker matrix status
        c_content = c_content.replace("{good:测试已冻结}", "{good:已通过验证}")
        # Update checklist
        c_content = re.sub(
            r"-\s*\[\s*\]\s*(启动 \*\*P2-GREEN\*\*.*)",
            r"- [x] 完成 **P2-GREEN**：业务实现与返工闭环落地，全部 37 项单测通过并通过 `scripts/gate.py --level L4` 门禁",
            c_content,
        )
        candidate_file.write_text(c_content, encoding="utf-8")
        sync_results["candidate_archify_updated"] = True

        # 3. Compile HTML via archify cli
        archify_cli = REPO_ROOT / ".agents/skills/archify/bin/archify.mjs"
        if archify_cli.exists():
            finalize_cmd = [
                "node",
                str(archify_cli),
                "finalize",
                "explainer",
                str(candidate_file),
                str(html_file),
                "--repo-root",
                ".",
                "--json",
            ]
            f_proc = subprocess.run(
                finalize_cmd,
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                check=False,
            )
            sync_results["archify_compile_code"] = f_proc.returncode
            sync_results["archify_compiled"] = f_proc.returncode == 0
            if f_proc.returncode == 0:
                try:
                    sync_results["archify_receipt"] = json.loads(f_proc.stdout)
                except Exception:
                    pass
            else:
                sync_results["error"] = f_proc.stderr or f_proc.stdout
        else:
            sync_results["archify_compiled"] = False
            sync_results["error"] = f"archify.mjs not found at {archify_cli}"

    return sync_results


def main():
    parser = argparse.ArgumentParser(description="Artemis Verification Gate")
    parser.add_argument(
        "--level",
        choices=["L1", "L2", "L3", "L4"],
        default="L4",
        help="Maximum level of gate checks to execute",
    )
    parser.add_argument(
        "--phase",
        choices=["P0-SPEC", "P1-RED", "P2-GREEN", "P3-REVIEW", "P4-BENCH"],
        default="P2-GREEN",
        help="Target phase for verification",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON report",
    )
    args = parser.parse_args()

    levels_order = ["L1", "L2", "L3", "L4"]
    max_idx = levels_order.index(args.level)

    report: dict[str, Any] = {
        "requested_level": args.level,
        "phase": args.phase,
        "all_passed": True,
        "gates": {},
    }

    # L1 Check
    if max_idx >= 0:
        l1 = check_l1_project_entry()
        report["gates"]["L1"] = l1
        if not l1["passed"]:
            report["all_passed"] = False

    # L2 Check
    if max_idx >= 1 and report["all_passed"]:
        l2 = check_l2_skills_installed()
        report["gates"]["L2"] = l2
        if not l2["passed"]:
            report["all_passed"] = False

    # L3 Check
    if max_idx >= 2 and report["all_passed"]:
        l3 = check_l3_dependencies_and_baseline()
        report["gates"]["L3"] = l3
        if not l3["passed"]:
            report["all_passed"] = False

    # L4 Check
    if max_idx >= 3 and report["all_passed"]:
        l4 = check_l4_unit_tests(args.phase)
        report["gates"]["L4"] = l4
        if not l4["passed"]:
            report["all_passed"] = False

    # Synchronize Task Board and Archify Board
    if report["all_passed"]:
        sync_res = sync_task_board(args.phase, report)
        report["sync"] = sync_res
        if sync_res.get("archify_compiled") is False:
            report["all_passed"] = False
            report["errors"] = ["Archify compilation failed"]

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        for lvl, res in report["gates"].items():
            status_str = "PASS" if res.get("passed") else "FAIL"
            print(f"[{status_str}] {lvl}: {res.get('summary', res.get('status', ''))}")
        print(f"\nFinal Gate Outcome: {'PASS' if report['all_passed'] else 'FAIL'}")

    sys.exit(0 if report["all_passed"] else 1)


if __name__ == "__main__":
    main()
