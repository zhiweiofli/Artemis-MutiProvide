"""业务规则单元测试：空间预算、回收顺序、清场名单、崩溃归类。"""

import importlib.util
from pathlib import Path

BASE = Path(__file__).resolve().parents[3] / "scripts" / "qa_daily"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, BASE / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


capacity = _load("qa_capacity", "rules/capacity.py")
cleanup = _load("qa_cleanup", "rules/cleanup.py")
recovery = _load("qa_recovery", "rules/recovery.py")


def test_size_text_is_parsed_from_the_detail_page():
    assert capacity.parse_size_gb("2179M") == 2.13
    assert capacity.parse_size_gb("1.9G") == 1.9
    assert capacity.parse_size_gb("2,179 MB") == 2.13
    assert capacity.parse_size_gb("大小 150.7M") == 0.15
    assert capacity.parse_size_gb("") is None


def test_reserve_is_three_times_the_package_size():
    assert capacity.required_gb(2.0) == 6.0
    assert capacity.required_gb(0.5) == 1.5
    assert capacity.required_gb(None) == 6.0  # 未知按 2 GB 估


def test_space_verdict_thresholds():
    assert capacity.verdict(free=10.0, need=6.0) == "ok"
    assert capacity.verdict(free=4.0, need=6.0) == "reclaim"
    assert capacity.verdict(free=1.0, need=6.0) == "blocked"


def test_reclaim_order_skips_protected_and_never_uninstalls_ninegame():
    history = ["com.a.game", "cn.ninegame.gamemanager", "com.b.game", "com.a.game", "com.current"]
    order = capacity.reclaim_order(history, protect={"com.current"})
    assert order == ["com.a.game", "com.b.game"]


def test_cleanup_refuses_to_touch_ninegame_itself():
    assert cleanup.SKIP == {"cn.ninegame.gamemanager", "cn.ninegame.launch.sample"}


def test_crash_classification_keeps_pass_and_marks_crash():
    # 没有崩溃证据时不改变原判
    recovery.crash_signature = lambda pkg: None
    assert recovery.classify("com.x", "D", "FAIL") == "FAIL"
    assert recovery.classify("com.x", "D", "PASS") == "PASS"
    recovery.crash_signature = lambda pkg: "FATAL EXCEPTION in com.x"
    assert recovery.classify("com.x", "D", "TIMEOUT") == "CRASH"
    assert recovery.classify("com.x", "D", "PASS") == "PASS"
