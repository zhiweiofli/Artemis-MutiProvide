"""S0-C3: a task locked to package A must refuse to run on package B's screen."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from artemis.agents.flash.runner import FlashRunner
from artemis.context import ArtemisContext
from artemis.graph.state import State


class _ExecutionSetup:
    """Minimal stand-in for ExecutionSetup carrying only the app lock."""

    def __init__(self, locked: str | None):
        self.video_recording_tools_enabled = False
        self.app_lock_status = (
            Mock(locked_app_package=locked) if locked else None
        )

    def get_locked_app_package(self) -> str | None:
        return self.app_lock_status.locked_app_package if self.app_lock_status else None


def _ctx(locked: str | None, data_engine=None):
    ctx = Mock(spec=ArtemisContext)
    ctx.execution_setup = _ExecutionSetup(locked)
    ctx.data_engine = data_engine
    ctx.step_memory = None
    ctx.device = Mock()
    return ctx


@pytest.mark.asyncio
async def test_refuses_to_start_when_another_app_owns_the_screen():
    engine = Mock()
    captured = AsyncMock()
    with (
        patch(
            "artemis.agents.flash.preflight.observe_foreground",
            AsyncMock(return_value=(False, "com.qjyx.android.ds.aligames", None)),
        ),
        patch("artemis.agents.flash.preflight._RETRY_SETTLE_SECONDS", 0.0),
        patch("artemis.agents.flash.preflight._FOREGROUND_POLL_SECONDS", 0.0),
        patch("artemis.agents.flash.runner.capture_screenshot_and_parse_ui", captured),
        patch("artemis.controllers.unified_controller.get_driver"),
        patch("artemis.agents.flash.runner.get_driver"),
    ):
        runner = FlashRunner(_ctx("com.qy.yjdn1.aligames", engine), goal="stage=BC")
        result = await runner.run(State(initial_goal="stage=BC"))

    assert result["status"] == "failed"
    assert result["preflight"] == "foreground_mismatch"
    assert "com.qy.yjdn1.aligames" in result["explanation"]
    assert "com.qjyx.android.ds.aligames" in result["explanation"]
    captured.assert_not_called()  # no frame captured, no LLM call
    checks = [
        c.kwargs for c in engine.record_trace.call_args_list
        if c.kwargs.get("name") == "foreground_check"
    ]
    assert len(checks) == 1
    assert checks[0]["status"] == "failed"
    assert checks[0]["payload"]["seen_package"] == "com.qjyx.android.ds.aligames"


@pytest.mark.asyncio
async def test_runs_normally_when_the_foreground_matches():
    with (
        patch(
            "artemis.agents.flash.preflight.observe_foreground",
            AsyncMock(return_value=(True, "com.qy.yjdn1.aligames", None)),
        ),
        patch(
            "artemis.agents.flash.runner.capture_screenshot_and_parse_ui",
            AsyncMock(return_value=("shot.png", b"IMG", "[1] x")),
        ),
        patch.object(FlashRunner, "_init_llm"),
        patch.object(FlashRunner, "_invoke_model", AsyncMock(return_value=None)),
        patch("artemis.controllers.unified_controller.get_driver"),
        patch("artemis.agents.flash.runner.get_driver"),
    ):
        runner = FlashRunner(_ctx("com.qy.yjdn1.aligames"), goal="stage=BC", max_turns=1)
        result = await runner.run(State(initial_goal="stage=BC"))

    assert result.get("preflight") is None


@pytest.mark.asyncio
async def test_unlocked_task_is_unaffected():
    with (
        patch("artemis.agents.flash.preflight.observe_foreground", AsyncMock()) as foreground,
        patch(
            "artemis.agents.flash.runner.capture_screenshot_and_parse_ui",
            AsyncMock(return_value=("shot.png", b"IMG", "[1] x")),
        ),
        patch.object(FlashRunner, "_init_llm"),
        patch.object(FlashRunner, "_invoke_model", AsyncMock(return_value=None)),
        patch("artemis.controllers.unified_controller.get_driver"),
        patch("artemis.agents.flash.runner.get_driver"),
    ):
        runner = FlashRunner(_ctx(None), goal="g", max_turns=1)
        await runner.run(State(initial_goal="g"))

    foreground.assert_not_called()
