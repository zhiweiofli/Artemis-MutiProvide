"""S0-L2: an E-stage report without a parseable verdict must not become PASS."""

from pathlib import Path
import importlib.util

_SPEC = importlib.util.spec_from_file_location(
    "qa_1114_queue", Path(__file__).resolve().parents[3] / "scripts" / "qa_1114_queue.py"
)
qa = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(qa)


def _phase(reported: str, timed_out: bool = False) -> dict:
    return {"phase": "E", "reported": reported, "timed_out": timed_out}


def test_report_without_result_or_status_is_inconclusive():
    phase = _phase("'explanation': '巡检大致完成，按钮基本正常'")
    assert qa.verdict_of(phase, 1200) == "UNKNOWN"
    assert qa.e_phase_verdict(phase, 1200) == "INCONCLUSIVE"


def test_empty_report_is_inconclusive():
    assert qa.e_phase_verdict(_phase(""), 1200) == "INCONCLUSIVE"


def test_explicit_verdicts_pass_through():
    assert qa.e_phase_verdict(_phase("stage=E result=PASS"), 1200) == "PASS"
    assert qa.e_phase_verdict(_phase("result=FAIL"), 1200) == "FAIL"
    assert qa.e_phase_verdict(_phase("result=PASS", timed_out=True), 1200) == "TIMEOUT"
