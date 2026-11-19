"""质检队列的判决解析：只认结构化 token，中英文同义写法归一，自述不算数。"""

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "qa_1114_queue", Path(__file__).resolve().parents[3] / "scripts" / "qa_1114_queue.py"
)
qa = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(qa)


def test_chinese_result_token_is_normalized():
    assert qa.verdict_of({"reported": "结果：PASS"}, 100) == "PASS"
    assert qa.verdict_of({"reported": "结论: FAIL"}, 100) == "FAIL"
    assert qa.verdict_of({"reported": "结果：BLOCKED"}, 100) == "BLOCKED"


def test_english_result_token_still_works():
    assert qa.verdict_of({"reported": "result=PASS"}, 100) == "PASS"
    assert qa.verdict_of({"reported": 'result: "fail"'}, 100) == "FAIL"


def test_gate_line_wins_over_the_model_text():
    assert qa.verdict_of({"gate": "FAIL", "reported": "结果：PASS"}, 100) == "FAIL"
    assert qa.verdict_of({"gate": "PASS", "reported": "结果：FAIL"}, 100) == "PASS"


def test_status_completed_alone_is_not_a_pass():
    assert qa.verdict_of({"reported": "'status': 'completed'"}, 100) == "UNKNOWN"


def test_character_name_drops_surrounding_quotes():
    assert qa.extract_character('角色名："阳夏彤"') == "阳夏彤"
    assert qa.extract_character("角色名：东门紫柔，等级 12") == "东门紫柔"
