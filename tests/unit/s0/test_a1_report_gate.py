"""S0-A1: a report is only a PASS when every acceptance check says YES with evidence."""

import importlib.util
from pathlib import Path
from unittest.mock import Mock

import pytest

from artemis.agents.flash.runner import FlashRunner
from artemis.agents.validator.tool_declarations import (
    ACCEPTANCE_CHECKS,
    REPORT_TASK_STATUS_TOOL,
    report_task_status_tool,
)
from artemis.context import ArtemisContext

_SPEC = importlib.util.spec_from_file_location(
    "qa_1114_queue", Path(__file__).resolve().parents[3] / "scripts" / "qa_1114_queue.py"
)
qa = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(qa)


def _report(**overrides):
    args = {
        "status": "completed",
        "explanation": "done",
        "check_guide_gone": "YES",
        "check_entry_visible": "YES",
        "check_panel_opened": "YES",
        "evidence": {
            "guide_gone": "shot_12.png",
            "entry_visible": "商城按钮 @ [900,1900]",
            "panel_opened": "¥168 首充面板",
        },
    }
    args.update(overrides)
    return args


def test_schema_only_requires_checks_when_asked():
    assert set(REPORT_TASK_STATUS_TOOL["function"]["parameters"]["required"]) == {
        "status",
        "explanation",
    }
    required = report_task_status_tool(True)["function"]["parameters"]["required"]
    assert set(ACCEPTANCE_CHECKS) <= set(required)
    assert "evidence" in required


@pytest.mark.parametrize(
    ("overrides", "verdict"),
    [
        ({}, None),
        ({"check_panel_opened": "NO"}, "FAIL"),
        ({"check_guide_gone": "NO"}, "FAIL"),
        ({"evidence": {"guide_gone": "a", "entry_visible": "", "panel_opened": "c"}}, "INCONCLUSIVE"),
        ({"evidence": None}, "INCONCLUSIVE"),
        ({"check_panel_opened": ""}, "INCONCLUSIVE"),
    ],
)
def test_gate_verdicts(overrides, verdict):
    assert FlashRunner._gate_report(_report(**overrides))[0] == verdict


@pytest.mark.asyncio
async def _run_finalize(args, monkeypatch):
    monkeypatch.setenv("ARTEMIS_FLASH_REPORT_CHECKS", "1")
    ctx = Mock(spec=ArtemisContext)
    ctx.data_engine = None
    ctx.device = Mock()
    ctx.adb_client = None
    ctx.driver = Mock()
    runner = FlashRunner(ctx, goal="stage=D")
    runner.summarizer = None
    return await runner._finalize_task_report(
        "report_task_status", args, "tc", "text", {}, b"pre", ["xml"], [], native_text=None
    )


@pytest.mark.asyncio
async def test_all_no_report_is_never_a_pass(monkeypatch):
    report = await _run_finalize(
        _report(check_entry_visible="NO", check_panel_opened="NO"), monkeypatch
    )
    assert report["verdict"] == "FAIL"
    assert report["status"] == "failed"
    assert report["gate_reason"] == "check_entry_visible=NO"


@pytest.mark.asyncio
async def test_empty_evidence_is_inconclusive(monkeypatch):
    report = await _run_finalize(
        _report(evidence={"guide_gone": "a", "entry_visible": "b", "panel_opened": ""}),
        monkeypatch,
    )
    assert report["verdict"] == "INCONCLUSIVE"
    assert report["status"] == "failed"


@pytest.mark.asyncio
async def test_full_yes_with_evidence_passes(monkeypatch):
    report = await _run_finalize(_report(), monkeypatch)
    assert report["verdict"] == "PASS"
    assert report["status"] == "completed"


@pytest.mark.asyncio
async def test_gate_is_off_by_default(monkeypatch):
    monkeypatch.delenv("ARTEMIS_FLASH_REPORT_CHECKS", raising=False)
    ctx = Mock(spec=ArtemisContext)
    ctx.data_engine = None
    ctx.device = Mock()
    ctx.adb_client = None
    ctx.driver = Mock()
    runner = FlashRunner(ctx, goal="open settings")
    runner.summarizer = None
    report = await runner._finalize_task_report(
        "report_task_status", {"status": "completed", "explanation": "ok"},
        "tc", "text", {}, b"pre", ["xml"], [], native_text=None,
    )
    assert report == {"status": "completed", "explanation": "ok"}


def test_queue_prefers_the_gate_line_and_completed_is_not_pass():
    assert qa.verdict_of({"gate": "FAIL", "reported": "result=PASS"}, 100) == "FAIL"
    assert qa.verdict_of({"reported": "'status': 'completed'"}, 100) == "UNKNOWN"
    assert qa.e_phase_verdict({"reported": "'status': 'completed'"}, 100) == "INCONCLUSIVE"
    assert qa.verdict_of({"gate": "PASS", "reported": ""}, 100) == "PASS"
