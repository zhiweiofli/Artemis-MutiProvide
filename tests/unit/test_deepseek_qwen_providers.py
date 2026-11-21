"""Unit tests for DeepSeek and Qwen provider adapters and reliability (T-05 ~ T-09).

Covers:
- T-05: ModelProvider mappings and ModelFactory credential bindings (including DASHSCOPE_API_KEY fallback and dedicated BASE_URL configs).
- T-06: Enforcement of stream_usage=True and max_retries=0 on ChatOpenAI instances.
- T-07: P-003 multimodal guard validation on operator primary and fallback nodes.
- T-08: RobustChatModelWrapper.with_structured_output protocol negotiation.
- T-09: HTTP 402 non-retryable fallback classification and prompt_cache_hit_tokens accounting via asynchronous FallbackRunner.
"""

from pathlib import Path
import tempfile
from pydantic import BaseModel, SecretStr
import pytest

from artemis.config import llm as config_llm
from artemis.config.settings import settings
from artemis.llm.google.usage import normalize_usage
from artemis.llm.reliability import FailureCategory, classify_failure
from artemis.llm.router import ModelEndpoint, ModelFactory, ModelProvider
from artemis.services.llm import RobustChatModelWrapper, _ObservedFallback

DETERMINISTIC_TEST_JSONC = """{
  "default": {
    "provider": "google",
    "model": "gemini-3.8-flash",
    "thinking_level": "medium",
    "is_multimodal": true,
    "fallback": {
      "provider": "google",
      "model": "gemini-3.7-flash",
      "thinking_level": "medium",
      "is_multimodal": true
    }
  },
  "active_preset": "gemini-baseline",
  "presets": {
    "gemini-flagship": {
      "planner": {"model": "gemini-3.8-flash"},
      "operator": {"model": "gemini-3.8-flash"}
    }
  },
  "presets_v2": {
    "gemini-baseline": {
      "default": {
        "provider": "google",
        "model": "gemini-3.8-flash",
        "thinking_level": "medium",
        "is_multimodal": true,
        "fallback": {
          "provider": "google",
          "model": "gemini-3.7-flash",
          "thinking_level": "medium",
          "is_multimodal": true
        }
      },
      "nodes": {
        "object_detector": {
          "provider": "google",
          "model": "gemini-robotics-er-2-preview",
          "coord_format": "point_yx_1000",
          "timeout": 10.0
        },
        "hopper": {
          "provider": "google",
          "model": "gemini-3.5-flash-lite"
        }
      }
    },
    "ds-qwen-hybrid": {
      "default": {
        "provider": "deepseek",
        "model": "deepseek-flash-v4-1017",
        "is_multimodal": true,
        "structured_output_method": "function_calling",
        "fallback": {
          "provider": "google",
          "model": "gemini-3.8-flash",
          "is_multimodal": true
        }
      },
      "nodes": {
        "object_detector": {
          "provider": "qwen",
          "model": "qwen2.5-vl-72b-instruct",
          "coord_format": "bbox_xyxy_px",
          "timeout": 25.0
        },
        "hopper": {
          "provider": "deepseek",
          "model": "deepseek-flash-v4-1017"
        }
      }
    },
    "ds-qwen-pure": {
      "default": {
        "provider": "deepseek",
        "model": "deepseek-flash-v4-1017",
        "is_multimodal": true,
        "structured_output_method": "function_calling",
        "fallback": {
          "provider": "qwen",
          "model": "qwen-vl-max-latest",
          "is_multimodal": true
        }
      },
      "nodes": {
        "object_detector": {
          "provider": "qwen",
          "model": "qwen2.5-vl-72b-instruct",
          "coord_format": "bbox_xyxy_px",
          "timeout": 25.0,
          "fallback": {
            "provider": "qwen",
            "model": "qwen-vl-max-latest",
            "coord_format": "bbox_xyxy_px"
          }
        },
        "hopper": {
          "provider": "deepseek",
          "model": "deepseek-flash-v4-1017"
        }
      }
    }
  },
  "nodes": {
    "operator": {
      "is_multimodal": true,
      "fallback": {
        "provider": "google",
        "model": "gemini-3.7-flash",
        "is_multimodal": true
      }
    }
  }
}"""


@pytest.fixture(autouse=True)
def _isolate_env_and_cache(monkeypatch, tmp_path=None):
    """Ensure complete isolation of environment variables, loaded settings, and configuration files."""
    ModelFactory._cache.clear()

    # Clear all sensitive, provider, and config path environment variables
    for env_var in (
        "ARTEMIS_PRESET",
        "ARTEMIS_FAKE_LLM",
        "ARTEMIS_ARTEMIS_JSONC",
        "ARTEMIS_ARTEMIS_JSON",
        "ARTEMIS_LLM_CONFIG_JSON",
        "ARTEMIS_CONFIG_DIR",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GCP_API_KEY",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "QWEN_API_KEY",
        "QWEN_BASE_URL",
        "DASHSCOPE_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "OPEN_ROUTER_API_KEY",
        "OCR_API_KEY",
        "VISION_API_KEY",
        "API_KEY",
        "OBJECT_DETECTOR_TIMEOUT",
    ):
        monkeypatch.delenv(env_var, raising=False)

    # Isolate module-level settings singleton attributes
    for attr in (
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "GCP_API_KEY",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "QWEN_API_KEY",
        "QWEN_BASE_URL",
        "DASHSCOPE_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "ANTHROPIC_API_KEY",
        "XAI_API_KEY",
        "OPEN_ROUTER_API_KEY",
        "OCR_API_KEY",
        "VISION_API_KEY",
        "API_KEY",
        "ARTEMIS_PRESET",
        "ARTEMIS_FAKE_LLM",
    ):
        if hasattr(settings, attr):
            monkeypatch.setattr(settings, attr, None, raising=False)

    created_temp_dir = None
    if tmp_path is None:
        created_temp_dir = tempfile.TemporaryDirectory(prefix="artemis_test_cfg_")
        temp_dir = Path(created_temp_dir.name)
    else:
        temp_dir = Path(tmp_path)

    temp_config_path = temp_dir / "artemis.jsonc"
    temp_config_path.write_text(DETERMINISTIC_TEST_JSONC, encoding="utf-8")
    monkeypatch.setenv("ARTEMIS_ARTEMIS_JSONC", str(temp_config_path))

    def _safe_get_config_path(candidate, *args, **kwargs):
        cand_str = str(candidate).lower()
        if "artemis" in cand_str or "llm-config" in cand_str:
            return temp_config_path
        from artemis.config.paths import get_config_path as _orig_get_config_path
        return _orig_get_config_path(candidate, *args, **kwargs)

    monkeypatch.setattr(config_llm, "get_config_path", _safe_get_config_path)

    yield

    ModelFactory._cache.clear()
    if created_temp_dir is not None:
        created_temp_dir.cleanup()


def test_t05_model_provider_mappings_and_factory_credentials(monkeypatch):
    """T-05: Verify ModelProvider.from_string supports deepseek, qwen, dashscope, bailian,
    and ModelFactory.create_model binds dedicated API_KEY and BASE_URL (with DASHSCOPE_API_KEY fallback).
    """
    assert hasattr(ModelProvider, "DEEPSEEK"), "ModelProvider.DEEPSEEK is not defined"
    assert hasattr(ModelProvider, "QWEN"), "ModelProvider.QWEN is not defined"

    # 1. from_string mappings
    assert ModelProvider.from_string("deepseek") == ModelProvider.DEEPSEEK
    assert ModelProvider.from_string("DeepSeek") == ModelProvider.DEEPSEEK
    assert ModelProvider.from_string("qwen") == ModelProvider.QWEN
    assert ModelProvider.from_string("dashscope") == ModelProvider.QWEN
    assert ModelProvider.from_string("bailian") == ModelProvider.QWEN

    # 2. Dedicated custom BASE_URL and API_KEY injection
    ModelFactory._cache.clear()
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-custom-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://custom.deepseek.test/v1")
    monkeypatch.setenv("QWEN_API_KEY", "sk-qwen-custom-key")
    monkeypatch.setenv("QWEN_BASE_URL", "https://custom.qwen.test/v1")

    ep_ds = ModelEndpoint(
        provider=ModelProvider.DEEPSEEK,
        model_name="deepseek-flash-v4-1017",
    )
    model_ds = ModelFactory.create_model(ep_ds)
    api_key_ds = getattr(model_ds, "openai_api_key", None) or getattr(model_ds, "api_key", None)
    if hasattr(api_key_ds, "get_secret_value"):
        api_key_ds = api_key_ds.get_secret_value()
    assert api_key_ds == "sk-ds-custom-key"

    base_url_ds = str(
        getattr(model_ds, "openai_api_base", None)
        or getattr(model_ds, "base_url", None)
        or getattr(getattr(model_ds, "client", None), "_base_url", "")
    ).rstrip("/")
    assert base_url_ds == "https://custom.deepseek.test/v1", (
        f"Expected complete base URL 'https://custom.deepseek.test/v1', got '{base_url_ds}'"
    )

    ep_qwen = ModelEndpoint(
        provider=ModelProvider.QWEN,
        model_name="qwen2.5-vl-72b-instruct",
    )
    model_qwen = ModelFactory.create_model(ep_qwen)
    api_key_qwen = getattr(model_qwen, "openai_api_key", None) or getattr(model_qwen, "api_key", None)
    if hasattr(api_key_qwen, "get_secret_value"):
        api_key_qwen = api_key_qwen.get_secret_value()
    assert api_key_qwen == "sk-qwen-custom-key"

    base_url_qwen = str(
        getattr(model_qwen, "openai_api_base", None)
        or getattr(model_qwen, "base_url", None)
        or getattr(getattr(model_qwen, "client", None), "_base_url", "")
    ).rstrip("/")
    assert base_url_qwen == "https://custom.qwen.test/v1", (
        f"Expected complete base URL 'https://custom.qwen.test/v1', got '{base_url_qwen}'"
    )

    # 3. Default base URLs when environment variables are unset
    ModelFactory._cache.clear()
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("QWEN_BASE_URL", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-default-key")
    monkeypatch.setenv("QWEN_API_KEY", "sk-qwen-default-key")

    model_ds_default = ModelFactory.create_model(ep_ds)
    default_url_ds = str(
        getattr(model_ds_default, "openai_api_base", None)
        or getattr(model_ds_default, "base_url", None)
        or getattr(getattr(model_ds_default, "client", None), "_base_url", "")
    ).rstrip("/")
    assert default_url_ds == "https://api.deepseek.com/v1", (
        f"Expected default DeepSeek URL 'https://api.deepseek.com/v1', got '{default_url_ds}'"
    )

    model_qwen_default = ModelFactory.create_model(ep_qwen)
    default_url_qwen = str(
        getattr(model_qwen_default, "openai_api_base", None)
        or getattr(model_qwen_default, "base_url", None)
        or getattr(getattr(model_qwen_default, "client", None), "_base_url", "")
    ).rstrip("/")
    assert default_url_qwen == "https://dashscope.aliyuncs.com/compatible-mode/v1", (
        f"Expected default Qwen DashScope URL 'https://dashscope.aliyuncs.com/compatible-mode/v1', got '{default_url_qwen}'"
    )

    # 4. QWEN fallback to DASHSCOPE_API_KEY when QWEN_API_KEY is not set
    ModelFactory._cache.clear()
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-dashscope-fallback-key")
    model_qwen_fb = ModelFactory.create_model(ep_qwen)
    api_key_fb = getattr(model_qwen_fb, "openai_api_key", None) or getattr(model_qwen_fb, "api_key", None)
    if hasattr(api_key_fb, "get_secret_value"):
        api_key_fb = api_key_fb.get_secret_value()
    assert api_key_fb == "sk-dashscope-fallback-key"


def test_t06_chatopenai_stream_usage_and_max_retries(monkeypatch):
    """T-06: Verify DEEPSEEK and QWEN ChatOpenAI instances enforce stream_usage=True and max_retries=0."""
    assert hasattr(ModelProvider, "DEEPSEEK"), "ModelProvider.DEEPSEEK is not defined"
    assert hasattr(ModelProvider, "QWEN"), "ModelProvider.QWEN is not defined"

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-key")
    monkeypatch.setenv("QWEN_API_KEY", "sk-test-key")

    ep_ds = ModelEndpoint(provider=ModelProvider.DEEPSEEK, model_name="deepseek-flash-v4-1017")
    m_ds = ModelFactory.create_model(ep_ds)
    assert getattr(m_ds, "stream_usage", None) is True, "DEEPSEEK ChatOpenAI must have stream_usage=True"
    assert getattr(m_ds, "max_retries", None) == 0, "DEEPSEEK ChatOpenAI must have max_retries=0"

    ep_qwen = ModelEndpoint(provider=ModelProvider.QWEN, model_name="qwen2.5-vl-72b-instruct")
    m_qwen = ModelFactory.create_model(ep_qwen)
    assert getattr(m_qwen, "stream_usage", None) is True, "QWEN ChatOpenAI must have stream_usage=True"
    assert getattr(m_qwen, "max_retries", None) == 0, "QWEN ChatOpenAI must have max_retries=0"


def test_t07_multimodal_guard_validation(monkeypatch):
    """T-07: P-003 multimodal guard validation:
    When operator primary model or fallback has is_multimodal=False,
    validate_providers() must raise a validation error during startup.
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-google-key")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", SecretStr("dummy-google-key"), raising=False)
    cfg = config_llm.parse_llm_config()

    assert hasattr(cfg.operator, "is_multimodal"), "LLM model has no is_multimodal attribute"

    # 1. Primary operator node configured with is_multimodal=False
    cfg.operator.is_multimodal = False
    with pytest.raises((ValueError, Exception), match="(?i)multimodal"):
        cfg.validate_providers()

    # Reset primary
    cfg.operator.is_multimodal = True

    # 2. Fallback operator node configured with is_multimodal=False
    assert cfg.operator.fallback is not None
    assert hasattr(cfg.operator.fallback, "is_multimodal"), "Fallback model has no is_multimodal attribute"
    cfg.operator.fallback.is_multimodal = False
    with pytest.raises((ValueError, Exception), match="(?i)multimodal"):
        cfg.validate_providers()


def test_t08_structured_output_protocol_negotiation():
    """T-08: Verify RobustChatModelWrapper.with_structured_output defaults to method='function_calling'
    for DEEPSEEK and QWEN endpoints, and respects endpoint.structured_output_method override.
    """
    assert hasattr(ModelProvider, "DEEPSEEK"), "ModelProvider.DEEPSEEK is not defined"
    assert hasattr(ModelProvider, "QWEN"), "ModelProvider.QWEN is not defined"
    assert (
        hasattr(ModelEndpoint, "model_fields")
        and "structured_output_method" in ModelEndpoint.model_fields
    ), "ModelEndpoint.structured_output_method is not defined"

    class DummySchema(BaseModel):
        field: str

    class MockBaseModel:
        def __init__(self):
            self.passed_schema = None
            self.passed_kwargs = {}

        def with_structured_output(self, schema, **kwargs):
            self.passed_schema = schema
            self.passed_kwargs = kwargs
            return self

    # 1. DEEPSEEK endpoint defaults to method="function_calling"
    mock1 = MockBaseModel()
    ep_ds = ModelEndpoint(
        provider=ModelProvider.DEEPSEEK,
        model_name="deepseek-flash-v4-1017",
        structured_output_method=None,
    )
    wrapper1 = RobustChatModelWrapper(mock1, endpoint=ep_ds)
    wrapper1.with_structured_output(DummySchema)
    assert mock1.passed_kwargs.get("method") == "function_calling"

    # 2. QWEN endpoint defaults to method="function_calling"
    mock2 = MockBaseModel()
    ep_qwen = ModelEndpoint(
        provider=ModelProvider.QWEN,
        model_name="qwen2.5-vl-72b-instruct",
        structured_output_method=None,
    )
    wrapper2 = RobustChatModelWrapper(mock2, endpoint=ep_qwen)
    wrapper2.with_structured_output(DummySchema)
    assert mock2.passed_kwargs.get("method") == "function_calling"

    # 3. endpoint.structured_output_method overrides default
    mock3 = MockBaseModel()
    ep_override = ModelEndpoint(
        provider=ModelProvider.DEEPSEEK,
        model_name="deepseek-flash-v4-1017",
        structured_output_method="json_mode",
    )
    wrapper3 = RobustChatModelWrapper(mock3, endpoint=ep_override)
    wrapper3.with_structured_output(DummySchema)
    assert mock3.passed_kwargs.get("method") == "json_mode"

    # 4. Caller explicit method kwarg takes precedence
    mock4 = MockBaseModel()
    wrapper4 = RobustChatModelWrapper(mock4, endpoint=ep_ds)
    wrapper4.with_structured_output(DummySchema, method="json_schema")
    assert mock4.passed_kwargs.get("method") == "json_schema"


@pytest.mark.asyncio
async def test_t09_http_402_fallback_and_cache_token_accounting():
    """T-09: Verify classify_failure on HTTP 402 returns retryable=False, should_fallback=True,
    _ObservedFallback immediately switches to fallback without retry, and normalize_usage extracts prompt_cache_hit_tokens.
    """
    class Http402Error(Exception):
        def __init__(self, message: str, status_code: int = 402):
            super().__init__(message)
            self.status_code = status_code
            self.code = status_code

    # 1. classify_failure on 402 / insufficient balance
    err1 = Http402Error("Insufficient balance in account")
    failure1 = classify_failure(err1)
    assert failure1.retryable is False, "402 must be classified as non-retryable"
    assert failure1.should_fallback is True, "402 must trigger fallback"
    assert failure1.category == FailureCategory.RATE_LIMIT

    err2 = RuntimeError("Account arrearage: insufficient_quota")
    failure2 = classify_failure(err2)
    assert failure2.retryable is False
    assert failure2.should_fallback is True
    assert failure2.category == FailureCategory.RATE_LIMIT

    # 2. _ObservedFallback switches immediately on 402 without retrying main
    history = []

    async def main_fn():
        history.append("main")
        raise Http402Error("insufficient balance")

    async def fallback_fn():
        history.append("fallback")
        return "fallback_success"

    runner = _ObservedFallback()
    result = await runner.run(main_fn, fallback_fn)
    assert result == "fallback_success"
    assert history == ["main", "fallback"]

    # 3. normalize_usage extraction of prompt_cache_hit_tokens
    payload1 = {
        "prompt_tokens": 200,
        "completion_tokens": 50,
        "prompt_cache_hit_tokens": 128,
    }
    norm1 = normalize_usage(payload1)
    assert norm1 is not None
    assert norm1["cached_tokens"] == 128, (
        f"Expected cached_tokens=128 from prompt_cache_hit_tokens, got {norm1.get('cached_tokens')}"
    )

    # Extraction of prompt_tokens_details.cached_tokens
    payload2 = {
        "input_tokens": 300,
        "output_tokens": 40,
        "prompt_tokens_details": {"cached_tokens": 96},
    }
    norm2 = normalize_usage(payload2)
    assert norm2 is not None
    assert norm2["cached_tokens"] == 96, (
        f"Expected cached_tokens=96 from prompt_tokens_details.cached_tokens, got {norm2.get('cached_tokens')}"
    )
