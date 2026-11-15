"""S0-L3: a degenerate frame must never reach a model.

The 12:37 incident: a 1x1 stand-in frame went to Qwen, which answered 400
"height(1) or width(1) must be larger than 28"; the classified error was
UNKNOWN, so the call fell back to gemini-robotics and died on API_KEY_INVALID.
"""

import base64
import io

import pytest
from langchain_core.messages import HumanMessage
from PIL import Image

from artemis.llm.reliability import FailureCategory, LLMPermanentError
from artemis.services.llm import (
    MIN_USABLE_IMAGE_EDGE,
    RobustChatModelWrapper,
    unusable_image_reason,
)


def _png(size: tuple[int, int], color="green") -> str:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _messages(url: str):
    return [HumanMessage(content=[{"type": "image_url", "image_url": {"url": url}}])]


def test_one_by_one_frame_is_rejected():
    reason = unusable_image_reason(_messages(_png((1, 1))))
    assert reason and "1x1" in reason


def test_small_frame_just_under_the_threshold_is_rejected():
    edge = MIN_USABLE_IMAGE_EDGE - 1
    assert unusable_image_reason(_messages(_png((edge, edge))))


def test_normal_screenshot_passes():
    assert unusable_image_reason(_messages(_png((1080, 2160)))) is None


def test_uniform_frame_is_allowed_but_flagged():
    # Black/white loading screens are real; they must not be blocked.
    assert unusable_image_reason(_messages(_png((1080, 2160), "black"))) is None


def test_undecodable_payload_is_left_to_the_provider():
    url = "data:image/jpeg;base64," + base64.b64encode(b"IMG").decode()
    assert unusable_image_reason(_messages(url)) is None


@pytest.mark.asyncio
async def test_degenerate_frame_never_calls_the_model():
    class Counting:
        calls = 0

        async def ainvoke(self, *args, **kwargs):
            Counting.calls += 1
            raise AssertionError("the model must not be called")

    wrapper = RobustChatModelWrapper(Counting())
    with pytest.raises(LLMPermanentError) as info:
        await wrapper.ainvoke(_messages(_png((1, 1))))

    assert Counting.calls == 0
    assert info.value.failure.category is FailureCategory.BAD_REQUEST
    assert info.value.failure.should_fallback is False  # no gemini handover


def test_driver_fails_closed_when_no_screenshot_can_be_taken():
    import asyncio
    from unittest.mock import MagicMock

    from artemis.drivers.android.adb_driver import AndroidAdbDriver

    device = MagicMock()
    device.screenshot.side_effect = RuntimeError("adb: device not found")
    driver = AndroidAdbDriver(device_id="dead-device", adb_client=device, ui_adb_client=None)

    with pytest.raises(RuntimeError) as info:
        asyncio.run(driver.get_screen_data(skip_settling=True))
    assert "no screenshot after a retake" in str(info.value)
