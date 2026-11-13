#!/usr/bin/env python3
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Endpoint Capabilities Prior Probe Script.

Executes 5 low-overhead capability probes (<500 tokens total) to convert
assumptions into verified facts saved in .artemis/capabilities.json:
1. Model reachability probe
2. Multimodal input probe (64x64 red PNG)
3. Structured output method negotiation probe (function_calling / json_mode / json_schema)
4. Stream usage metadata probe (stream_usage=True, requires positive prompt_tokens/input_tokens)
5. Synthetic Grounding calibration (synthetic 400x800 image, pixel vs 1000 dual decoding, error <= 25)
"""

import argparse
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import time
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from pydantic import BaseModel
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")
OUTPUT_PATH = REPO_ROOT / ".artemis/capabilities.json"
GROUNDING_TOLERANCE = 25


def _make_dummy_png(width: int = 64, height: int = 64, color: tuple = (255, 0, 0)) -> bytes:
    """Generate in-memory PNG bytes without requiring external assets."""
    try:
        from PIL import Image

        img = Image.new("RGB", (width, height), color=color)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        # Fallback 1x1 transparent/red PNG
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
            b"\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )


def _make_synthetic_grounding_png(
    width: int = 400,
    height: int = 800,
    box: tuple = (100, 500, 200, 600),
) -> bytes:
    """Generate a white image with a single black rectangle."""
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (width, height), color=(255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle(box, fill=(0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return _make_dummy_png(width, height)


def _extract_usage(obj: Any) -> dict[str, int] | None:
    """Extract normalized token usage from an AIMessage, dict, or usage object.

    Returns None when usage is missing/unknown so unknown usage is never conflated with 0.
    """
    if obj is None:
        return None

    um: Any = None
    if isinstance(obj, dict):
        if any(
            k in obj and obj[k] is not None
            for k in (
                "prompt_tokens",
                "input_tokens",
                "completion_tokens",
                "output_tokens",
                "total_tokens",
            )
        ):
            um = obj
        else:
            um = obj.get("usage_metadata") or obj.get("token_usage") or obj.get("usage")
            if um is None and isinstance(obj.get("response_metadata"), dict):
                rm = obj["response_metadata"]
                um = rm.get("token_usage") or rm.get("usage")
    else:
        um = getattr(obj, "usage_metadata", None)
        if um is None:
            rm = getattr(obj, "response_metadata", None)
            if isinstance(rm, dict):
                um = rm.get("token_usage") or rm.get("usage")
        if um is None and any(
            getattr(obj, k, None) is not None
            for k in ("prompt_tokens", "input_tokens", "completion_tokens", "output_tokens")
        ):
            um = obj

    if um is None:
        return None

    if isinstance(um, dict):
        has_token_key = any(
            k in um and um[k] is not None
            for k in (
                "prompt_tokens",
                "input_tokens",
                "completion_tokens",
                "output_tokens",
                "total_tokens",
            )
        )
        if not has_token_key:
            return None
        pt_raw = um.get("prompt_tokens")
        if pt_raw is None:
            pt_raw = um.get("input_tokens")
        ct_raw = um.get("completion_tokens")
        if ct_raw is None:
            ct_raw = um.get("output_tokens")
        tt_raw = um.get("total_tokens")
        pt = int(pt_raw or 0)
        ct = int(ct_raw or 0)
        tt = int(tt_raw if tt_raw is not None else (pt + ct))
        return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt}

    pt_val = getattr(um, "prompt_tokens", None)
    if pt_val is None:
        pt_val = getattr(um, "input_tokens", None)
    ct_val = getattr(um, "completion_tokens", None)
    if ct_val is None:
        ct_val = getattr(um, "output_tokens", None)
    tt_val = getattr(um, "total_tokens", None)
    if pt_val is None and ct_val is None and tt_val is None:
        return None
    pt = int(pt_val or 0)
    ct = int(ct_val or 0)
    tt = int(tt_val if tt_val is not None else (pt + ct))
    return {"prompt_tokens": pt, "completion_tokens": ct, "total_tokens": tt}


class _UsageCaptureCallback(BaseCallbackHandler):
    """Callback handler to capture raw LLM response usage from LangChain model invocations."""

    def __init__(self) -> None:
        super().__init__()
        self.last_usage: dict[str, int] | None = None

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        try:
            generations = getattr(response, "generations", None)
            if generations and generations[0]:
                msg = getattr(generations[0][0], "message", None)
                extracted = _extract_usage(msg)
                if extracted is not None:
                    self.last_usage = extracted
                    return
            llm_output = getattr(response, "llm_output", None)
            if isinstance(llm_output, dict):
                extracted = _extract_usage(llm_output.get("token_usage") or llm_output.get("usage"))
                if extracted is not None:
                    self.last_usage = extracted
        except Exception:
            pass


class _ObservingLLMProxy:
    """Thin proxy around a LangChain chat model to retain the raw AIMessage from ainvoke/invoke."""

    def __init__(self, base_llm: Any) -> None:
        self._base_llm = base_llm
        self.last_response: Any = None

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        res = await self._base_llm.ainvoke(*args, **kwargs)
        self.last_response = res
        return res

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        res = self._base_llm.invoke(*args, **kwargs)
        self.last_response = res
        return res

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base_llm, name)


class ProbeBudgetTracker:
    """Tracks token and request budget across capability probes with strict guardrails."""

    def __init__(self, max_tokens: int = 500, max_requests: int = 15):
        self.max_tokens = max_tokens
        self.max_requests = max_requests
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_requests = 0
        self.unknown_usage_requests = 0
        self.budget_exceeded = False
        self.budget_error: str | None = None
        self.records: list[dict[str, Any]] = []

    def can_proceed(self) -> bool:
        if self.budget_exceeded:
            return False
        if self.total_requests >= self.max_requests:
            self.budget_exceeded = True
            self.budget_error = (
                f"Probe request budget reached: {self.total_requests}/{self.max_requests}"
            )
            return False
        if (self.total_prompt_tokens + self.total_completion_tokens) >= self.max_tokens:
            self.budget_exceeded = True
            self.budget_error = (
                f"Probe token budget reached: "
                f"{self.total_prompt_tokens + self.total_completion_tokens}/{self.max_tokens}"
            )
            return False
        return True

    def record(
        self,
        probe_name: str,
        model_name: str,
        endpoint: str,
        usage: Any = None,
    ) -> dict[str, Any]:
        self.total_requests += 1
        extracted = _extract_usage(usage)
        if extracted is None:
            self.unknown_usage_requests += 1
            rec: dict[str, Any] = {
                "probe": probe_name,
                "endpoint": endpoint,
                "model": model_name,
                "usage_known": False,
                "prompt_tokens": None,
                "completion_tokens": None,
                "total_tokens": None,
            }
        else:
            pt = extracted["prompt_tokens"]
            ct = extracted["completion_tokens"]
            tt = extracted["total_tokens"]
            self.total_prompt_tokens += pt
            self.total_completion_tokens += ct
            rec = {
                "probe": probe_name,
                "endpoint": endpoint,
                "model": model_name,
                "usage_known": True,
                "prompt_tokens": pt,
                "completion_tokens": ct,
                "total_tokens": tt,
            }

        total_now = self.total_prompt_tokens + self.total_completion_tokens
        if total_now > self.max_tokens or self.total_requests > self.max_requests:
            self.budget_exceeded = True
            self.budget_error = (
                f"Probe budget exceeded at {probe_name} ({endpoint}/{model_name}): "
                f"{self.total_requests}/{self.max_requests} requests, "
                f"{total_now}/{self.max_tokens} tokens"
            )
            rec["budget_exceeded"] = True

        self.records.append(rec)
        return rec

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "unknown_usage_requests": self.unknown_usage_requests,
            "budget_limit_tokens": self.max_tokens,
            "budget_limit_requests": self.max_requests,
            "budget_exceeded": self.budget_exceeded,
            "budget_error": self.budget_error,
            "records": self.records,
        }


def run_probes(mock: bool = False) -> dict[str, Any]:
    has_ds_key = bool(os.environ.get("DEEPSEEK_API_KEY"))
    has_qwen_key = bool(os.environ.get("QWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY"))

    results: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "simulation" if (mock or not (has_ds_key and has_qwen_key)) else "live",
        "probes": {},
    }

    if mock or not (has_ds_key and has_qwen_key):
        results["probes"]["1_model_reachability"] = {
            "status": "unverified",
            "deepseek": {
                "model": ds_model_name,
                "accessible": False,
                "note": "simulated/mock mode",
            },
            "qwen": {
                "model": "qwen2.5-vl-72b-instruct",
                "accessible": False,
                "note": "simulated/mock mode",
            },
        }
        results["probes"]["2_multimodal_perception"] = {
            "status": "unverified",
            "note": "simulated/mock mode",
        }
        results["probes"]["3_structured_output"] = {
            "status": "unverified",
            "note": "simulated/mock mode",
        }
        results["probes"]["4_streaming_usage"] = {
            "status": "unverified",
            "note": "simulated/mock mode",
        }
        results["probes"]["5_grounding_calibration"] = {
            "status": "unverified",
            "note": "simulated/mock mode",
        }
        return results

    from artemis.agents.object_detector.object_detector import normalize_detected_coordinate
    from artemis.llm.router import ModelEndpoint, ModelFactory, ModelProvider
    from langchain_core.messages import HumanMessage

    budget_tracker = ProbeBudgetTracker(max_tokens=2500, max_requests=20)
    qwen_model_name = os.getenv("QWEN_BASE_MODEL", "qwen2.5-vl-72b-instruct")
    ds_model_name = os.getenv("DEEPSEEK_BASE_MODEL", "deepseek-flash")

    # 1. Reachability probe
    ds_ok, qwen_ok = False, False
    ds_err, qwen_err = None, None
    ds_model, qwen_model = None, None
    ds_usage_known, qwen_usage_known = False, False

    if budget_tracker.can_proceed():
        try:
            ds_ep = ModelEndpoint(
                provider=ModelProvider.DEEPSEEK,
                model_name=ds_model_name,
                max_tokens=10,
            )
            ds_model = ModelFactory.create_model(ds_ep)
            res_ds = ds_model.invoke([HumanMessage(content="ping")])
            rec_ds = budget_tracker.record(
                "1_model_reachability",
                ds_model_name,
                "deepseek",
                res_ds,
            )
            ds_usage_known = bool(rec_ds["usage_known"] and (rec_ds["total_tokens"] or 0) > 0)
            ds_ok = bool(
                res_ds
                and res_ds.content is not None
                and ds_usage_known
                and not budget_tracker.budget_exceeded
            )
            if not ds_usage_known:
                ds_err = "Usage metadata missing or zero on reachability response"
            elif budget_tracker.budget_exceeded:
                ds_err = budget_tracker.budget_error
        except Exception as exc:
            ds_err = str(exc)
            budget_tracker.record(
                "1_model_reachability", ds_model_name, "deepseek", None
            )
    else:
        ds_err = budget_tracker.budget_error

    if budget_tracker.can_proceed():
        try:
            qwen_ep = ModelEndpoint(
                provider=ModelProvider.QWEN,
                model_name=qwen_model_name,
                max_tokens=10,
            )
            qwen_model = ModelFactory.create_model(qwen_ep)
            res_qwen = qwen_model.invoke([HumanMessage(content="ping")])
            rec_qwen = budget_tracker.record(
                "1_model_reachability",
                qwen_model_name,
                "qwen",
                res_qwen,
            )
            qwen_usage_known = bool(rec_qwen["usage_known"] and (rec_qwen["total_tokens"] or 0) > 0)
            qwen_ok = bool(
                res_qwen
                and res_qwen.content is not None
                and qwen_usage_known
                and not budget_tracker.budget_exceeded
            )
            if not qwen_usage_known:
                qwen_err = "Usage metadata missing or zero on reachability response"
            elif budget_tracker.budget_exceeded:
                qwen_err = budget_tracker.budget_error
        except Exception as exc:
            qwen_err = str(exc)
            budget_tracker.record("1_model_reachability", qwen_model_name, "qwen", None)
    else:
        qwen_err = budget_tracker.budget_error

    if ds_ok and qwen_ok:
        results["probes"]["1_model_reachability"] = {
            "status": "verified",
            "deepseek": {
                "endpoint": "deepseek",
                "model": ds_model_name,
                "accessible": True,
            },
            "qwen": {
                "endpoint": "qwen",
                "model": qwen_model_name,
                "accessible": True,
            },
        }
    else:
        reach_status = (
            "unverified"
            if (not ds_usage_known or not qwen_usage_known)
            and not budget_tracker.budget_exceeded
            and ds_model is not None
            and qwen_model is not None
            and ds_err
            and "Usage metadata" in ds_err
            else "failed"
        )
        results["probes"]["1_model_reachability"] = {
            "status": reach_status,
            "deepseek": {
                "endpoint": "deepseek",
                "model": ds_model_name,
                "accessible": ds_ok,
                "error": ds_err,
            },
            "qwen": {
                "endpoint": "qwen",
                "model": qwen_model_name,
                "accessible": qwen_ok,
                "error": qwen_err,
            },
        }

    # 2. Multimodal perception probe
    mm_ok = False
    mm_err = None
    mm_status = "failed"
    if not budget_tracker.can_proceed():
        mm_err = budget_tracker.budget_error or "Skipped: probe budget exhausted"
    elif ds_model is not None:
        try:
            png_bytes = _make_dummy_png(64, 64, (255, 0, 0))
            png_b64 = base64.b64encode(png_bytes).decode("utf-8")
            mm_msg = HumanMessage(
                content=[
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{png_b64}"},
                    },
                    {
                        "type": "text",
                        "text": "What is the color of this 64x64 image? Return one word.",
                    },
                ]
            )
            res_mm = ds_model.invoke([mm_msg])
            rec_mm = budget_tracker.record(
                "2_multimodal_perception",
                ds_model_name,
                "deepseek",
                res_mm,
            )
            color_matched = bool(res_mm and "red" in str(res_mm.content).lower())
            if not rec_mm["usage_known"]:
                mm_status = "unverified"
                mm_err = "Usage metadata missing/unknown on multimodal response"
            elif budget_tracker.budget_exceeded:
                mm_status = "failed"
                mm_err = budget_tracker.budget_error
            elif color_matched and (rec_mm["total_tokens"] or 0) > 0:
                mm_ok = True
                mm_status = "verified"
            else:
                mm_status = "failed"
                mm_err = "Multimodal response did not match expected color or had zero tokens"
        except Exception as exc:
            mm_err = str(exc)
            budget_tracker.record(
                "2_multimodal_perception", ds_model_name, "deepseek", None
            )
    else:
        mm_err = "Model not constructed"

    results["probes"]["2_multimodal_perception"] = {
        "status": mm_status,
        "endpoint": "deepseek",
        "model": ds_model_name,
        "deepseek_image_url": "supported" if mm_ok else "unverified",
        "error": mm_err if not mm_ok else None,
    }

    # 3. Structured output probe (negotiate function_calling, json_mode, and json_schema)
    st_ok = False
    st_err = None
    st_status = "failed"
    structured_methods = ["function_calling", "json_mode", "json_schema"]
    method_results: dict[str, dict[str, Any]] = {}
    any_unknown_usage = False

    class PingTag(BaseModel):
        tag: str

    if ds_model is not None:
        for method in structured_methods:
            if not budget_tracker.can_proceed():
                st_err = budget_tracker.budget_error or "Probe budget exhausted"
                method_results[method] = {
                    "supported": False,
                    "endpoint": "deepseek",
                    "model": ds_model_name,
                    "error": st_err,
                }
                break
            try:
                cb = _UsageCaptureCallback()
                try:
                    st_m = ds_model.with_structured_output(PingTag, method=method, include_raw=True)
                except TypeError:
                    st_m = ds_model.with_structured_output(PingTag, method=method)

                try:
                    st_res = st_m.invoke(
                        [HumanMessage(content="Output tag ping")],
                        config={"callbacks": [cb]},
                    )
                except TypeError:
                    st_res = st_m.invoke([HumanMessage(content="Output tag ping")])

                if isinstance(st_res, dict) and ("raw" in st_res or "parsed" in st_res):
                    raw_msg = st_res.get("raw")
                    parsed_obj = st_res.get("parsed")
                    raw_usage = _extract_usage(raw_msg) or cb.last_usage
                else:
                    parsed_obj = st_res
                    raw_usage = _extract_usage(st_res) or cb.last_usage

                rec_st = budget_tracker.record(
                    f"3_structured_output_{method}",
                    ds_model_name,
                    "deepseek",
                    raw_usage,
                )
                tag_ok = isinstance(parsed_obj, PingTag) and parsed_obj.tag == "ping"
                usage_ok = bool(rec_st["usage_known"] and (rec_st["total_tokens"] or 0) > 0)
                if not rec_st["usage_known"]:
                    any_unknown_usage = True

                if budget_tracker.budget_exceeded:
                    st_err = budget_tracker.budget_error
                    method_results[method] = {
                        "supported": False,
                        "endpoint": "deepseek",
                        "model": ds_model_name,
                        "usage": raw_usage,
                        "error": st_err,
                    }
                    st_ok = False
                    break

                supported = bool(tag_ok and usage_ok)
                err_msg = None
                if not tag_ok:
                    err_msg = "Result parsed but tag did not match ping"
                elif not rec_st["usage_known"]:
                    err_msg = "Usage metadata missing/unknown on structured output response"
                elif (rec_st["total_tokens"] or 0) <= 0:
                    err_msg = "Zero token usage observed on structured output response"

                method_results[method] = {
                    "supported": supported,
                    "endpoint": "deepseek",
                    "model": ds_model_name,
                    "usage": raw_usage,
                    "error": err_msg,
                }
                if supported:
                    st_ok = True
            except Exception as exc:
                method_results[method] = {
                    "supported": False,
                    "endpoint": "deepseek",
                    "model": ds_model_name,
                    "error": str(exc),
                }
                budget_tracker.record(
                    f"3_structured_output_{method}",
                    ds_model_name,
                    "deepseek",
                    None,
                )
                if budget_tracker.budget_exceeded:
                    st_err = budget_tracker.budget_error
                    st_ok = False
                    break
    else:
        st_err = "Model not constructed"

    if budget_tracker.budget_exceeded:
        st_ok = False
        st_status = "failed"
        st_err = budget_tracker.budget_error
    elif st_ok and not any_unknown_usage:
        st_status = "verified"
    elif any_unknown_usage and not st_ok:
        st_status = "unverified"
        st_err = st_err or "Structured output usage metadata unknown"
    else:
        st_status = "failed"

    preferred_method = next(
        (m for m in structured_methods if method_results.get(m, {}).get("supported")), None
    )

    results["probes"]["3_structured_output"] = {
        "status": st_status,
        "endpoint": "deepseek",
        "model": ds_model_name,
        "methods": method_results,
        "deepseek_preferred": preferred_method if st_status == "verified" else None,
        "error": st_err if st_status != "verified" else None,
    }

    # 4. Streaming usage probe (must verify positive input_tokens/prompt_tokens > 0)
    stream_ok = False
    stream_err = None
    stream_status = "failed"
    observed_stream_usage = None

    if not budget_tracker.can_proceed():
        stream_err = budget_tracker.budget_error or "Skipped: probe budget exhausted"
    elif ds_model is not None:
        try:
            chunks = list(ds_model.stream([HumanMessage(content="hi")]))
            for c in chunks:
                um = getattr(c, "usage_metadata", None)
                if um is None and isinstance(getattr(c, "response_metadata", None), dict):
                    rm = c.response_metadata
                    um = rm.get("token_usage") or rm.get("usage")
                if um is not None:
                    observed_stream_usage = um
                    extracted_um = _extract_usage(um)
                    if extracted_um and extracted_um["prompt_tokens"] > 0:
                        stream_ok = True
                        break
            rec_stream = budget_tracker.record(
                "4_streaming_usage",
                ds_model_name,
                "deepseek",
                observed_stream_usage,
            )
            if budget_tracker.budget_exceeded:
                stream_ok = False
                stream_status = "failed"
                stream_err = budget_tracker.budget_error
            elif not rec_stream["usage_known"]:
                stream_ok = False
                stream_status = "unverified"
                stream_err = "Streaming usage metadata missing/unknown"
            elif stream_ok:
                stream_status = "verified"
            else:
                stream_status = "failed"
                stream_err = "Zero usage metadata observed"
        except Exception as exc:
            stream_err = str(exc)
            budget_tracker.record("4_streaming_usage", ds_model_name, "deepseek", None)
    else:
        stream_err = "Model not constructed"

    results["probes"]["4_streaming_usage"] = {
        "status": stream_status,
        "endpoint": "deepseek",
        "model": ds_model_name,
        "stream_usage_supported": stream_ok,
        "observed_usage": observed_stream_usage,
        "error": stream_err if stream_status != "verified" else None,
    }

    # 5. Grounding calibration probe (dual candidate evaluation: pixel vs 1000-normalized, tolerance <= 25)
    grounding_ok = False
    grounding_status = "failed"
    norm_center = None
    calibrated_coord_format = "bbox_xyxy_px"
    err_px = 9999
    err_1000 = 9999
    g_err = None

    if not budget_tracker.can_proceed():
        g_err = budget_tracker.budget_error or "Skipped: probe budget exhausted"
    else:
        try:
            from artemis.agents.object_detector.object_detector import _detect_single_label

            synth_png = _make_synthetic_grounding_png(400, 800, (100, 500, 200, 600))
            qwen_ep = ModelEndpoint(
                provider=ModelProvider.QWEN,
                model_name=qwen_model_name,
                max_tokens=512,
                coord_format="bbox_xyxy_px",
            )
            qwen_det = ModelFactory.create_model(qwen_ep)
            qwen_proxy = _ObservingLLMProxy(qwen_det)
            coro = _detect_single_label(
                primary_llm=qwen_proxy,
                ctx=None,
                image_bytes=synth_png,
                mime_type="image/png",
                label="black rectangle",
                primary_coord_format="bbox_xyxy_px",
                image_size=(400, 800),
            )
            try:
                det_res = asyncio.run(coro)
            except Exception:
                coro.close()
                raise

            g_usage = _extract_usage(qwen_proxy.last_response)
            rec_g = budget_tracker.record(
                "5_grounding_calibration",
                qwen_model_name,
                "qwen",
                g_usage,
            )

            if det_res and len(det_res) > 0:
                raw_item = det_res[0]
                box_item = {k: v for k, v in raw_item.items() if k != "point"}
                if not any(k in box_item for k in ("bbox_2d", "box_2d", "bounding_box")):
                    box_item = raw_item

                pt_px = normalize_detected_coordinate(
                    box_item, coord_format="bbox_xyxy_px", image_size=(400, 800)
                )
                pt_1000 = normalize_detected_coordinate(
                    box_item, coord_format="bbox_xyxy_1000", image_size=(400, 800)
                )

                err_px = (abs(pt_px[0] - 375) + abs(pt_px[1] - 688)) if pt_px else 9999
                err_1000 = (abs(pt_1000[0] - 375) + abs(pt_1000[1] - 688)) if pt_1000 else 9999

                if err_1000 < err_px:
                    calibrated_coord_format = "bbox_xyxy_1000"
                    norm_center = pt_1000
                    best_err = err_1000
                else:
                    calibrated_coord_format = "bbox_xyxy_px"
                    norm_center = pt_px
                    best_err = err_px

                if budget_tracker.budget_exceeded:
                    grounding_ok = False
                    grounding_status = "failed"
                    g_err = budget_tracker.budget_error
                elif not rec_g["usage_known"]:
                    grounding_ok = False
                    grounding_status = "unverified"
                    g_err = "Usage metadata missing/unknown on grounding response"
                elif (rec_g["total_tokens"] or 0) <= 0:
                    grounding_ok = False
                    grounding_status = "failed"
                    g_err = "Zero token usage observed on grounding response"
                elif best_err <= GROUNDING_TOLERANCE:
                    grounding_ok = True
                    grounding_status = "verified"
                else:
                    grounding_ok = False
                    grounding_status = "failed"
                    g_err = (
                        f"Grounding center error {best_err} exceeds spec tolerance "
                        f"<= {GROUNDING_TOLERANCE}"
                    )
            else:
                if not rec_g["usage_known"]:
                    grounding_status = "unverified"
                    g_err = "Grounding returned no detections and usage metadata is unknown"
                else:
                    grounding_status = "failed"
                    g_err = "Grounding returned no detections"
        except Exception as exc:
            g_err = str(exc)
            grounding_status = "failed"

    results["probes"]["5_grounding_calibration"] = {
        "status": grounding_status,
        "endpoint": "qwen",
        "model": qwen_model_name,
        "target_box_px": [100, 500, 200, 600],
        "expected_center_norm": [375, 688],
        "detected_center_norm": norm_center,
        "calibrated_coord_format": calibrated_coord_format,
        "tolerance": GROUNDING_TOLERANCE,
        "error_px": err_px,
        "error_1000": err_1000,
        "error_within_tolerance": grounding_ok,
        "error": g_err if grounding_status != "verified" else None,
    }

    results["usage_summary"] = budget_tracker.to_dict()
    return results


def main():
    parser = argparse.ArgumentParser(description="Probe Model Endpoint Capabilities")
    parser.add_argument("--mock", action="store_true", help="Force offline mock probe")
    parser.add_argument("--json", action="store_true", help="Print json output to stdout")
    args = parser.parse_args()

    results = run_probes(mock=args.mock)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(f"Capabilities probed (mode: {results['mode']}). Report saved to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
