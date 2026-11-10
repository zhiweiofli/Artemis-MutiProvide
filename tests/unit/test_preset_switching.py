"""Unit tests for preset switching and resolution (T-01 ~ T-04).

Covers:
- T-01: resolve_preset_config priority (explicit_preset > ARTEMIS_PRESET > active_preset) and unknown preset validation.
- T-02: Top-level presets backward compatibility and presets_v2 full topology expansion.
- T-03: Provider inheritance leak prevention (cross-vendor model mismatch).
- T-04: Phase 2 Zero-Google invariant for ds-qwen-pure preset across all AgentNode and LLMUtilsNode.
"""

import copy
from pathlib import Path
import tempfile
from typing import get_args
import pytest

from artemis.config.constants import AgentNode, LLMUtilsNode
from artemis.config import llm as config_llm
from artemis.config.settings import settings
from artemis.llm.router import ModelFactory
from artemis.services import llm as llm_service

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


def test_t01_preset_switching_priority(monkeypatch):
    """T-01: Verify resolve_preset_config priority: explicit_preset > ARTEMIS_PRESET > active_preset,
    and unknown preset raises ValueError.
    """
    assert hasattr(config_llm, "resolve_preset_config"), (
        "resolve_preset_config is not implemented in artemis.config.llm"
    )
    resolve_preset_config = config_llm.resolve_preset_config

    sample_config = {
        "active_preset": "gemini-baseline",
        "presets_v2": {
            "gemini-baseline": {
                "default": {
                    "provider": "google",
                    "model": "model-active-baseline",
                },
                "nodes": {},
            },
            "ds-qwen-hybrid": {
                "default": {
                    "provider": "deepseek",
                    "model": "model-env-hybrid",
                },
                "nodes": {},
            },
            "ds-qwen-pure": {
                "default": {
                    "provider": "deepseek",
                    "model": "model-explicit-pure",
                },
                "nodes": {},
            },
        },
    }

    # 1. Unknown preset raises ValueError immediately
    with pytest.raises(ValueError, match="(?i)unknown preset"):
        resolve_preset_config(sample_config, explicit_preset="unknown-preset-xyz")

    # 2. explicit_preset takes highest precedence over ARTEMIS_PRESET env var and active_preset
    monkeypatch.setenv("ARTEMIS_PRESET", "ds-qwen-hybrid")
    if hasattr(settings, "ARTEMIS_PRESET"):
        monkeypatch.setattr(settings, "ARTEMIS_PRESET", "ds-qwen-hybrid", raising=False)
    res_explicit = resolve_preset_config(sample_config, explicit_preset="ds-qwen-pure")
    assert res_explicit["default"]["provider"] == "deepseek"
    assert res_explicit["default"]["model"] == "model-explicit-pure"

    # 3. ARTEMIS_PRESET env var takes precedence over active_preset when explicit is None
    monkeypatch.setenv("ARTEMIS_PRESET", "ds-qwen-hybrid")
    if hasattr(settings, "ARTEMIS_PRESET"):
        monkeypatch.setattr(settings, "ARTEMIS_PRESET", "ds-qwen-hybrid", raising=False)
    res_env = resolve_preset_config(sample_config, explicit_preset=None)
    assert res_env["default"]["provider"] == "deepseek"
    assert res_env["default"]["model"] == "model-env-hybrid"

    # 4. active_preset is used as fallback when neither explicit nor env var is provided
    monkeypatch.delenv("ARTEMIS_PRESET", raising=False)
    if hasattr(settings, "ARTEMIS_PRESET"):
        monkeypatch.setattr(settings, "ARTEMIS_PRESET", None, raising=False)
    res_active = resolve_preset_config(sample_config, explicit_preset=None)
    assert res_active["default"]["provider"] == "google"
    assert res_active["default"]["model"] == "model-active-baseline"


def test_t02_presets_v2_expansion_and_presets_compat():
    """T-02: Verify top-level presets stays readable for Admin Console compatibility,
    and presets_v2 expands gemini-baseline, ds-qwen-hybrid, and ds-qwen-pure.
    """
    assert hasattr(config_llm, "resolve_preset_config"), (
        "resolve_preset_config is not implemented in artemis.config.llm"
    )
    resolve_preset_config = config_llm.resolve_preset_config

    sample_config = {
        "active_preset": "gemini-baseline",
        "presets": {
            "gemini-flagship": {
                "planner": {"model": "gemini-3.8-flash"},
                "operator": {"model": "gemini-3.8-flash"},
            }
        },
        "presets_v2": {
            "gemini-baseline": {
                "default": {
                    "provider": "google",
                    "model": "gemini-3.8-flash",
                    "thinking_level": "medium",
                    "is_multimodal": True,
                    "fallback": {
                        "provider": "google",
                        "model": "gemini-3.7-flash",
                        "thinking_level": "medium",
                        "is_multimodal": True,
                    },
                },
                "nodes": {
                    "object_detector": {
                        "provider": "google",
                        "model": "gemini-robotics-er-2-preview",
                        "coord_format": "point_yx_1000",
                        "timeout": 10.0,
                    },
                    "hopper": {
                        "provider": "google",
                        "model": "gemini-3.5-flash-lite",
                    },
                },
            },
            "ds-qwen-hybrid": {
                "default": {
                    "provider": "deepseek",
                    "model": "deepseek-flash-v4-1017",
                    "is_multimodal": True,
                    "structured_output_method": "function_calling",
                    "fallback": {
                        "provider": "google",
                        "model": "gemini-3.8-flash",
                        "is_multimodal": True,
                    },
                },
                "nodes": {
                    "object_detector": {
                        "provider": "qwen",
                        "model": "qwen2.5-vl-72b-instruct",
                        "coord_format": "bbox_xyxy_px",
                        "timeout": 25.0,
                    },
                    "hopper": {
                        "provider": "deepseek",
                        "model": "deepseek-flash-v4-1017",
                    },
                },
            },
            "ds-qwen-pure": {
                "default": {
                    "provider": "deepseek",
                    "model": "deepseek-flash-v4-1017",
                    "is_multimodal": True,
                    "structured_output_method": "function_calling",
                    "fallback": {
                        "provider": "qwen",
                        "model": "qwen-vl-max-latest",
                        "is_multimodal": True,
                    },
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
                            "coord_format": "bbox_xyxy_px",
                        },
                    },
                    "hopper": {
                        "provider": "deepseek",
                        "model": "deepseek-flash-v4-1017",
                    },
                },
            },
        },
    }

    # Deepcopy original legacy presets before resolution to ensure caller input is untouched
    original_legacy_presets = copy.deepcopy(sample_config["presets"])

    # Verify expansion of gemini-baseline
    expanded_base = resolve_preset_config(sample_config, explicit_preset="gemini-baseline")
    assert expanded_base["default"]["provider"] == "google"
    assert expanded_base["nodes"]["object_detector"]["coord_format"] == "point_yx_1000"

    # Verify expansion of ds-qwen-hybrid
    expanded_hybrid = resolve_preset_config(sample_config, explicit_preset="ds-qwen-hybrid")
    assert expanded_hybrid["default"]["provider"] == "deepseek"
    assert expanded_hybrid["default"]["fallback"]["provider"] == "google"
    assert expanded_hybrid["nodes"]["object_detector"]["provider"] == "qwen"
    assert expanded_hybrid["nodes"]["object_detector"]["coord_format"] == "bbox_xyxy_px"

    # Verify expansion of ds-qwen-pure
    expanded_pure = resolve_preset_config(sample_config, explicit_preset="ds-qwen-pure")
    assert expanded_pure["default"]["provider"] == "deepseek"
    assert expanded_pure["default"]["fallback"]["provider"] == "qwen"
    assert expanded_pure["nodes"]["object_detector"]["provider"] == "qwen"
    assert expanded_pure["nodes"]["object_detector"]["fallback"]["provider"] == "qwen"

    # Verify top-level presets remains intact and completely unchanged after resolutions
    assert "presets" in sample_config
    assert sample_config["presets"] == original_legacy_presets
    assert "gemini-flagship" in sample_config["presets"]


def test_t03_prevent_provider_inheritance_leak():
    """T-03: Provider inheritance leak prevention:
    When default is deepseek and a node specifies model: 'gemini-3.5-flash-lite' without provider,
    the loader must raise ValueError to block cross-vendor inheritance leak.
    """
    assert hasattr(config_llm, "resolve_preset_config"), (
        "resolve_preset_config is not implemented in artemis.config.llm"
    )
    resolve_preset_config = config_llm.resolve_preset_config

    leak_config = {
        "active_preset": "leak-test",
        "presets_v2": {
            "leak-test": {
                "default": {
                    "provider": "deepseek",
                    "model": "deepseek-flash-v4-1017",
                },
                "nodes": {
                    "hopper": {
                        # Omitted provider; model is gemini-*, which conflicts with default provider deepseek!
                        "model": "gemini-3.5-flash-lite",
                    }
                },
            }
        },
    }

    with pytest.raises(ValueError, match="(?i)(provider|conflict|mismatch|leak|gemini)"):
        resolve_preset_config(leak_config, explicit_preset="leak-test")


def test_t04_zero_google_invariant_phase2(monkeypatch):
    """T-04: Phase 2 Zero-Google invariant:
    With GOOGLE_API_KEY cleared and ARTEMIS_PRESET=ds-qwen-pure,
    all AgentNode, LLMUtilsNode, lightweight judge nodes, and get_llm_for_model(None, ctx=ctx)
    must resolve to non-Google endpoints, and get_google_llm must never be called.
    """
    assert hasattr(llm_service, "get_llm_for_model"), (
        "get_llm_for_model is not implemented in artemis.services.llm"
    )
    get_llm_for_model = llm_service.get_llm_for_model

    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("ARTEMIS_PRESET", "ds-qwen-pure")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-ds-dummy-key")
    monkeypatch.setenv("QWEN_API_KEY", "sk-qwen-dummy-key")
    monkeypatch.setattr(settings, "GOOGLE_API_KEY", None, raising=False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", None, raising=False)

    # Poison get_google_llm to ensure it is never called
    def _forbidden_google_llm(*args, **kwargs):
        raise RuntimeError("Forbidden Google backdoor called in ds-qwen-pure preset!")

    monkeypatch.setattr(llm_service, "get_google_llm", _forbidden_google_llm)

    # Load configuration
    cfg = config_llm.parse_llm_config()

    class DummyContext:
        def __init__(self, c):
            self.llm_config = c
            self.session_id = "test-session-zero-google"

    ctx = DummyContext(cfg)

    # Exhaustive enumeration directly from Literal types to prevent silent omission of nodes
    all_agent_nodes = list(get_args(AgentNode))
    all_utils_nodes = list(get_args(LLMUtilsNode))

    forbidden_providers = {"google", "vertexai", "vertex"}

    for node in all_agent_nodes:
        ep = llm_service._resolve_endpoint(ctx, node, is_utils=False)
        assert ep.provider.value not in forbidden_providers, (
            f"Agent node '{node}' resolved to Google provider: {ep.provider}"
        )
        ep_fb = llm_service._resolve_endpoint(ctx, node, is_utils=False, use_fallback=True)
        assert ep_fb.provider.value not in forbidden_providers, (
            f"Agent node '{node}' fallback resolved to Google provider: {ep_fb.provider}"
        )

    for util in all_utils_nodes:
        ep = llm_service._resolve_endpoint(ctx, util, is_utils=True)
        assert ep.provider.value not in forbidden_providers, (
            f"Utils node '{util}' resolved to Google provider: {ep.provider}"
        )
        ep_fb = llm_service._resolve_endpoint(ctx, util, is_utils=True, use_fallback=True)
        assert ep_fb.provider.value not in forbidden_providers, (
            f"Utils node '{util}' fallback resolved to Google provider: {ep_fb.provider}"
        )

    # Lightweight judge nodes
    for judge in ("validator_pixel_safety_net", "planner_validation"):
        j_cfg = cfg.get_agent(judge)
        assert j_cfg.provider not in forbidden_providers, (
            f"Judge '{judge}' has Google provider: {j_cfg.provider}"
        )
        if j_cfg.fallback:
            assert j_cfg.fallback.provider not in forbidden_providers, (
                f"Judge '{judge}' fallback has Google provider: {j_cfg.fallback.provider}"
            )

    # get_llm_for_model(None, ctx=ctx)
    wrapper = get_llm_for_model(None, ctx=ctx)
    assert wrapper.endpoint.provider.value not in forbidden_providers, (
        f"get_llm_for_model resolved to Google provider: {wrapper.endpoint.provider}"
    )
