"""单实例锁：一轮没跑完，第二轮必须被挡下（2026-11-18 差点并发抢设备）。"""

import importlib.util
import multiprocessing as mp
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "qa_runlock", Path(__file__).resolve().parents[3] / "scripts" / "qa_daily" / "runlock.py"
)
runlock = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runlock)


def _hold(path: Path, seconds: float) -> None:
    import importlib.util as iu

    spec = iu.spec_from_file_location("qa_runlock_holder", path)
    mod = iu.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.try_acquire("holder")
    import time

    time.sleep(seconds)


def test_second_process_is_refused_while_the_first_holds_the_lock():
    lock_file = Path(runlock.__file__)
    proc = mp.Process(target=_hold, args=(lock_file, 3.0))
    proc.start()
    try:
        import time

        time.sleep(0.5)
        ok, note = runlock.try_acquire("second")
        assert ok is False
        assert "另一轮" in note
    finally:
        proc.join(timeout=5)


def test_lock_is_free_again_after_the_holder_exits():
    lock_file = Path(runlock.__file__)
    proc = mp.Process(target=_hold, args=(lock_file, 0.5))
    proc.start()
    proc.join(timeout=5)
    ok, note = runlock.try_acquire("after")
    assert ok is True, note
