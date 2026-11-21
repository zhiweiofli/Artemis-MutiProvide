"""S0-B1: a real OpenAI-SDK 400 must be BAD_REQUEST and fail after one attempt.

``openai.BadRequestError.code`` is the string ``'invalid_request_error'``; it
used to shadow ``status_code=400`` and route the call to UNKNOWN -> retry ->
llm_pause.
"""

import httpx
import openai
import pytest

from artemis.llm.reliability import (
    FailureCategory,
    LLMPermanentError,
    classify_failure,
    extract_status_code,
)
from artemis.services import llm as llm_service
from artemis.services.llm import RobustChatModelWrapper


def _deepseek_400() -> openai.BadRequestError:
    req = httpx.Request("POST", "https://api.deepseek.com/chat/completions")
    body = {
        "message": "deepseek-reasoner does not support this tool_choice",
        "type": "invalid_request_error",
        "param": None,
        "code": "invalid_request_error",
    }
    resp = httpx.Response(400, request=req, json={"error": body})
    return openai.BadRequestError(f"Error code: 400 - {{'error': {body}}}", response=resp, body=body)


def test_string_code_does_not_shadow_status_code():
    err = _deepseek_400()
    assert err.code == "invalid_request_error"
    assert err.__cause__ is None  # the chain is empty: recursing __cause__ cannot help
    assert extract_status_code(err) == 400
    failure = classify_failure(err)
    assert failure.category is FailureCategory.BAD_REQUEST
    assert not failure.retryable


@pytest.mark.parametrize(
    ("attrs", "message", "expected"),
    [
        ({"status_code": 429, "code": "rate_limit"}, "x", 429),
        ({"code": "503"}, "x", 503),
        ({"status": 401}, "x", 401),
        ({"code": "invalid_request_error"}, "Error code: 400 - {...}", 400),
        ({"code": True}, "nothing numeric", None),
        ({}, "something odd", None),
    ],
)
def test_extraction_order_and_regex_fallback(attrs, message, expected):
    class E(Exception):
        pass

    err = E(message)
    for key, value in attrs.items():
        setattr(err, key, value)
    assert extract_status_code(err) == expected


def test_qwen_tiny_image_400_is_bad_request():
    """The 1x1-frame Qwen error surfaced as UNKNOWN and triggered the Gemini fallback."""
    err = RuntimeError(
        "Error code: 400 - {'code': 20015, 'message': 'height(1) or width(1) must be"
        " larger than 28 for Qwen 3 VL models.', 'data': None}"
    )
    failure = classify_failure(err)
    assert failure.category is FailureCategory.BAD_REQUEST
    assert not failure.should_fallback


@pytest.mark.asyncio
async def test_mock_400_raises_permanent_after_one_attempt(monkeypatch, tmp_path):
    pause_file = tmp_path / ".artemis_paused"
    monkeypatch.setattr(llm_service, "PAUSE_FILE", pause_file)
    llm_service._ENDPOINT_BREAKER._states.clear()
    paused = []
    monkeypatch.setattr(
        llm_service, "_handle_llm_pause_and_resume", lambda e: paused.append(e) or pause_file
    )

    class Always400:
        calls = 0

        async def ainvoke(self, *args, **kwargs):
            Always400.calls += 1
            raise _deepseek_400()

    wrapper = RobustChatModelWrapper(Always400())
    with pytest.raises(LLMPermanentError) as info:
        await wrapper.ainvoke([])
    assert Always400.calls == 1
    assert info.value.failure.category is FailureCategory.BAD_REQUEST
    assert paused == []
    assert not pause_file.exists()
