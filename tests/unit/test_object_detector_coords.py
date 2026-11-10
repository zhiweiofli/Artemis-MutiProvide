"""Unit tests for Object Detector coordinate normalization and fallback loop (T-10 ~ T-12).

Covers:
- T-10: Golden fixtures coordinate normalization for 5 coordinate formats.
- T-11: Degenerate, inverted, and malformed coordinate filtering and clamping.
- T-12: Detector timeout / 503 and fallback closed-loop execution with distinct primary and fallback coordinate formats.
"""

from pathlib import Path
import tempfile
from langchain_core.messages import AIMessage
import pytest

from artemis.agents.object_detector import object_detector as detector_mod
from artemis.agents.object_detector.object_detector import _run_object_detection
from artemis.config import llm as config_llm
from artemis.config.settings import settings
from artemis.llm.router import ModelEndpoint, ModelFactory, ModelProvider
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


def test_t10_golden_fixtures_coordinate_normalization():
    """T-10: Golden Fixtures coordinate normalization for:
    point_yx_1000, point_xy_1000, bbox_yxyx_1000, bbox_xyxy_1000, bbox_xyxy_px (with image_size=(1080, 2400)).
    All outputs must be [x, y] in [0, 1000] without double flipping.
    """
    assert hasattr(detector_mod, "normalize_detected_coordinate"), (
        "normalize_detected_coordinate is not implemented in object_detector"
    )
    normalize_detected_coordinate = detector_mod.normalize_detected_coordinate

    # 1. point_yx_1000: Gemini ER default {"point": [y, x]} in 0..1000 -> canonical [x, y]
    item_yx = {"point": [200, 800]}
    res_yx = normalize_detected_coordinate(item_yx, coord_format="point_yx_1000")
    assert res_yx == [800, 200], f"Expected [800, 200], got {res_yx}"

    # 2. point_xy_1000: Standard point {"point": [x, y]} in 0..1000 -> canonical [x, y]
    item_xy = {"point": [800, 200]}
    res_xy = normalize_detected_coordinate(item_xy, coord_format="point_xy_1000")
    assert res_xy == [800, 200], f"Expected [800, 200], got {res_xy}"

    # 3. bbox_yxyx_1000: Gemini box {"box_2d": [ymin, xmin, ymax, xmax]} -> center [cx, cy]
    item_yxyx = {"box_2d": [100, 200, 300, 600]}
    res_yxyx = normalize_detected_coordinate(item_yxyx, coord_format="bbox_yxyx_1000")
    # cx = (200 + 600) / 2 = 400, cy = (100 + 300) / 2 = 200
    assert res_yxyx == [400, 200], f"Expected [400, 200], got {res_yxyx}"

    # 4. bbox_xyxy_1000: Qwen normalized {"bbox_2d": [xmin, ymin, xmax, ymax]} -> center [cx, cy]
    item_xyxy = {"bbox_2d": [200, 100, 600, 300]}
    res_xyxy = normalize_detected_coordinate(item_xyxy, coord_format="bbox_xyxy_1000")
    # cx = (200 + 600) / 2 = 400, cy = (100 + 300) / 2 = 200
    assert res_xyxy == [400, 200], f"Expected [400, 200], got {res_xyxy}"

    # 5. bbox_xyxy_px: Bailian Qwen2.5-VL absolute pixels with image_size=(1080, 2400)
    # xmin=108, ymin=240, xmax=324, ymax=720
    # cx = (108 + 324) / 2 = 216 px -> 216 / 1080 * 1000 = 200
    # cy = (240 + 720) / 2 = 480 px -> 480 / 2400 * 1000 = 200
    item_px = {"bbox_2d": [108, 240, 324, 720]}
    res_px = normalize_detected_coordinate(
        item_px, coord_format="bbox_xyxy_px", image_size=(1080, 2400)
    )
    assert res_px == [200, 200], f"Expected [200, 200], got {res_px}"


def test_t11_degenerate_and_malformed_coordinate_filtering():
    """T-11: Malformed and degenerate coordinate filtering:
    Inverted boxes, zero-area boxes, out-of-bounds coords, missing image_size for bbox_xyxy_px,
    and non-numeric fields must be rejected (return None) or properly clamped.
    """
    assert hasattr(detector_mod, "normalize_detected_coordinate"), (
        "normalize_detected_coordinate is not implemented in object_detector"
    )
    normalize_detected_coordinate = detector_mod.normalize_detected_coordinate

    # 1. Inverted box (xmax <= xmin or ymax <= ymin) -> None
    assert (
        normalize_detected_coordinate(
            {"bbox_2d": [500, 500, 200, 200]}, coord_format="bbox_xyxy_1000"
        )
        is None
    )
    assert (
        normalize_detected_coordinate(
            {"box_2d": [600, 200, 100, 400]}, coord_format="bbox_yxyx_1000"
        )
        is None
    )

    # 2. Zero-area box (xmin == xmax or ymin == ymax) -> None
    assert (
        normalize_detected_coordinate(
            {"bbox_2d": [100, 100, 100, 200]}, coord_format="bbox_xyxy_1000"
        )
        is None
    )
    assert (
        normalize_detected_coordinate(
            {"bbox_2d": [100, 200, 300, 200]}, coord_format="bbox_xyxy_1000"
        )
        is None
    )

    # 3. bbox_xyxy_px without valid image_size -> None
    assert (
        normalize_detected_coordinate(
            {"bbox_2d": [100, 200, 300, 400]}, coord_format="bbox_xyxy_px", image_size=None
        )
        is None
    )
    assert (
        normalize_detected_coordinate(
            {"bbox_2d": [100, 200, 300, 400]}, coord_format="bbox_xyxy_px", image_size=(0, 0)
        )
        is None
    )
    assert (
        normalize_detected_coordinate(
            {"bbox_2d": [100, 200, 300, 400]},
            coord_format="bbox_xyxy_px",
            image_size=(-1080, 2400),
        )
        is None
    )

    # 4. Non-numeric fields in points or boxes -> None
    assert (
        normalize_detected_coordinate({"point": ["abc", 500]}, coord_format="point_yx_1000")
        is None
    )
    assert (
        normalize_detected_coordinate(
            {"bbox_2d": [100, "xyz", 300, 400]}, coord_format="bbox_xyxy_1000"
        )
        is None
    )

    # 5. Non-dict input -> None
    assert normalize_detected_coordinate("not a dict", coord_format="point_yx_1000") is None
    assert normalize_detected_coordinate(None, coord_format="point_yx_1000") is None
    assert normalize_detected_coordinate([], coord_format="point_yx_1000") is None

    # 6. Coordinate clamping for out-of-bounds coordinates
    # Point [-50, 1200] in point_xy_1000 should be clamped to [0, 1000]
    res_clamped = normalize_detected_coordinate(
        {"point": [-50, 1200]}, coord_format="point_xy_1000"
    )
    assert res_clamped == [0, 1000], f"Expected [0, 1000], got {res_clamped}"


@pytest.mark.asyncio
async def test_t12_detector_timeout_and_fallback_closed_loop(monkeypatch):
    """T-12: Detector timeout and fallback closed-loop:
    When primary detector throws TimeoutError or HTTP 503, _run_object_detection automatically
    triggers configured fallback model per-label and parses results according to fallback's coord_format.
    """
    class Http503Error(Exception):
        def __init__(self, message: str = "Service Unavailable", status_code: int = 503):
            super().__init__(message)
            self.status_code = status_code

    class MockDetector:
        def __init__(self, endpoint, failure=None, response=None):
            self.endpoint = endpoint
            self.failure = failure
            self.response = response
            self.calls = 0
            self.calls_by_label: dict[str, int] = {}
            self.unmatched_calls = 0

        @staticmethod
        def _extract_prompt_text(args, kwargs) -> str:
            parts: list[str] = []
            for item in list(args) + list(kwargs.values()):
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, (list, tuple)):
                    for sub in item:
                        content = getattr(sub, "content", sub)
                        if isinstance(content, str):
                            parts.append(content)
                        elif isinstance(content, list):
                            for block in content:
                                if isinstance(block, dict) and block.get("type") != "image_url":
                                    if "text" in block:
                                        parts.append(str(block["text"]))
                                elif isinstance(block, str):
                                    parts.append(block)
                        else:
                            parts.append(str(content))
                else:
                    content = getattr(item, "content", None)
                    if isinstance(content, str):
                        parts.append(content)
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") != "image_url":
                                if "text" in block:
                                    parts.append(str(block["text"]))
                            elif isinstance(block, str):
                                parts.append(block)
                    else:
                        parts.append(str(item))
            return " ".join(parts)

        async def ainvoke(self, *args, **kwargs):
            self.calls += 1
            call_text = self._extract_prompt_text(args, kwargs)
            matched_labels = [
                label for label in ("submit_button", "missing_button") if label in call_text
            ]
            if len(matched_labels) == 1 and "{labels_str}" not in call_text:
                matched_label = matched_labels[0]
                self.calls_by_label[matched_label] = (
                    self.calls_by_label.get(matched_label, 0) + 1
                )
            else:
                matched_label = None
                self.unmatched_calls += 1
                for label in matched_labels:
                    self.calls_by_label[label] = self.calls_by_label.get(label, 0) + 1

            if self.failure:
                raise self.failure

            if self.response is not None:
                return self.response

            if matched_label == "submit_button":
                return AIMessage(
                    content='[{"bbox_2d": [200, 100, 600, 300], "label": "submit_button"}]'
                )
            if matched_label == "missing_button":
                return AIMessage(content="[]")
            return AIMessage(content="[]")

    class DummyNodeConfig:
        def __init__(self, coord_format, fallback=None):
            self.coord_format = coord_format
            self.fallback = fallback
            self.timeout = 5.0

    class DummyConfig:
        def __init__(self):
            self.object_detector = DummyNodeConfig(
                coord_format="bbox_yxyx_1000",
                fallback=DummyNodeConfig(coord_format="bbox_xyxy_1000"),
            )
            self.timeout = 5.0

        def get_utils(self, name):
            if name == "object_detector":
                return self.object_detector
            raise KeyError(name)

    class DummyContext:
        def __init__(self):
            self.llm_config = DummyConfig()

    # 1x1 dummy PNG image bytes
    dummy_img = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
        b"\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    # Test both TimeoutError and HTTP 503 failure modes
    error_scenarios = [
        TimeoutError("Primary detector timed out after 10.0s"),
        Http503Error("Primary detector failed with HTTP 503 Service Unavailable"),
    ]

    for primary_error in error_scenarios:
        # Primary endpoint uses bbox_yxyx_1000 format; Fallback endpoint uses bbox_xyxy_1000 format
        if hasattr(ModelEndpoint, "model_fields") and "coord_format" in ModelEndpoint.model_fields:
            primary_endpoint = ModelEndpoint(
                provider=ModelProvider.GOOGLE,
                model_name="gemini-robotics-er-2-preview",
                coord_format="bbox_yxyx_1000",
            )
            fallback_provider = ModelProvider.QWEN if hasattr(ModelProvider, "QWEN") else ModelProvider.CUSTOM
            fallback_endpoint = ModelEndpoint(
                provider=fallback_provider,
                model_name="qwen-vl-max-latest",
                coord_format="bbox_xyxy_1000",
            )
        else:
            class DummyEndpoint:
                def __init__(self, provider, model_name, coord_format):
                    self.provider = provider
                    self.model_name = model_name
                    self.coord_format = coord_format

            primary_endpoint = DummyEndpoint(
                provider="google",
                model_name="gemini-robotics-er-2-preview",
                coord_format="bbox_yxyx_1000",
            )
            fallback_endpoint = DummyEndpoint(
                provider="qwen",
                model_name="qwen-vl-max-latest",
                coord_format="bbox_xyxy_1000",
            )

        primary_model = MockDetector(primary_endpoint, failure=primary_error)
        fallback_model = MockDetector(fallback_endpoint)

        recorded_calls = []

        def mock_get_llm(ctx, name: str, is_utils: bool = False, use_fallback: bool = False, **kwargs):
            recorded_calls.append({
                "name": name,
                "is_utils": is_utils,
                "use_fallback": use_fallback,
            })
            if use_fallback:
                return fallback_model
            return primary_model

        monkeypatch.setattr(detector_mod, "get_llm", mock_get_llm)
        monkeypatch.setattr(llm_service, "get_llm", mock_get_llm)

        ctx = DummyContext()
        queries = ["submit_button", "missing_button"]

        result = await _run_object_detection(
            ctx,
            image_bytes=dummy_img,
            queries=queries,
            global_timeout=5.0,
        )

        # 1. Assert get_llm routing parameters (R3a)
        assert len(recorded_calls) >= 2, "Expected get_llm calls for primary and fallback"
        for call in recorded_calls:
            if call["name"] == "object_detector":
                assert call["is_utils"] is True, (
                    f"get_llm call for object_detector must specify is_utils=True, got: {call}"
                )

        primary_route = any(
            c["name"] == "object_detector" and c["is_utils"] is True and not c["use_fallback"]
            for c in recorded_calls
        )
        assert primary_route, "get_llm was not called with name='object_detector', is_utils=True, use_fallback=False"

        fallback_route = any(
            c["name"] == "object_detector" and c["is_utils"] is True and c["use_fallback"]
            for c in recorded_calls
        )
        assert fallback_route, "get_llm was not called with name='object_detector', is_utils=True, use_fallback=True"

        # 2. Assert calls per query and expanded label set (R3b)
        assert primary_model.calls == len(queries), (
            f"Primary detector must be called once per query ({len(queries)}) for {type(primary_error).__name__}, got {primary_model.calls}"
        )
        assert fallback_model.calls == len(queries), (
            f"Fallback detector must be called once per query ({len(queries)}) for {type(primary_error).__name__}, got {fallback_model.calls}"
        )
        for q in queries:
            assert primary_model.calls_by_label.get(q, 0) == 1, (
                f"Primary detector must be called exactly once for '{q}' under "
                f"{type(primary_error).__name__}, got {primary_model.calls_by_label.get(q, 0)} "
                f"(calls_by_label={primary_model.calls_by_label})"
            )
            assert fallback_model.calls_by_label.get(q, 0) == 1, (
                f"Fallback detector must be called exactly once for '{q}' under "
                f"{type(primary_error).__name__}, got {fallback_model.calls_by_label.get(q, 0)} "
                f"(calls_by_label={fallback_model.calls_by_label})"
            )
        assert set(primary_model.calls_by_label.keys()) == set(queries), (
            f"Primary detector requested label set {set(primary_model.calls_by_label.keys())} "
            f"must equal {set(queries)}"
        )
        assert set(fallback_model.calls_by_label.keys()) == set(queries), (
            f"Fallback detector requested label set {set(fallback_model.calls_by_label.keys())} "
            f"must equal {set(queries)}"
        )
        assert primary_model.unmatched_calls == 0, (
            f"Primary detector received {primary_model.unmatched_calls} unmatched/ambiguous label calls"
        )
        assert fallback_model.unmatched_calls == 0, (
            f"Fallback detector received {fallback_model.unmatched_calls} unmatched/ambiguous label calls"
        )

        # 3. Assert detection results normalized according to fallback's coord_format (bbox_xyxy_1000):
        # Under bbox_xyxy_1000 [xmin, ymin, xmax, ymax] = [200, 100, 600, 300]:
        # cx = (200 + 600) / 2 = 400, cy = (100 + 300) / 2 = 200 -> canonical [400, 200]
        # (If erroneously parsed as primary's bbox_yxyx_1000, cx would be 200, cy 400 -> [200, 400])
        assert "detected" in result, f"Expected 'detected' key in result, got {result}"
        detected_list = result["detected"]
        assert len(detected_list) == 1, f"Expected 1 detected item, got {detected_list}"

        detected_item = detected_list[0]
        assert detected_item.get("label") == "submit_button"
        assert detected_item.get("point") == [400, 200], (
            f"Expected canonical point [400, 200] parsed with fallback's bbox_xyxy_1000 format, "
            f"got {detected_item.get('point')}"
        )

        # 4. Assert failed and detected results are exact and non-overlapping (R3a)
        assert "failed" in result, f"Expected 'failed' key in result, got {result}"
        failed_list = result["failed"]

        detected_labels = [d.get("label") for d in detected_list if isinstance(d, dict)]
        assert detected_labels == ["submit_button"]
        assert set(failed_list) == {"missing_button"}, (
            f"Expected failed list to exactly contain ['missing_button'], got {failed_list}"
        )
        assert set(detected_labels).isdisjoint(set(failed_list)), (
            f"Detected labels {detected_labels} and failed labels {failed_list} must not overlap"
        )
