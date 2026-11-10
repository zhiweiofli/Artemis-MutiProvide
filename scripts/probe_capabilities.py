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
4. Stream usage metadata probe (stream_usage=True)
5. Synthetic Grounding calibration (synthetic 400x800 image)
"""

import argparse
import asyncio
import base64
import io
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / ".artemis/capabilities.json"


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


def run_probes(mock: bool = False) -> dict[str, Any]:
    has_ds_key = bool(os.environ.get("DEEPSEEK_API_KEY"))
    has_qwen_key = bool(os.environ.get("QWEN_API_KEY") or os.environ.get("DASHSCOPE_API_KEY"))

    results: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "mode": "simulation" if (mock or not (has_ds_key and has_qwen_key)) else "live",
        "probes": {},
    }

    if mock or not (has_ds_key and has_qwen_key):
        # Deterministic simulation based on confirmed provider specifications
        results["probes"]["1_model_reachability"] = {
            "status": "unverified",
            "deepseek": {
                "model": "deepseek-flash-v4-1017",
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

    # Live probing logic when keys are present: execute genuine calls via ModelFactory
    from artemis.llm.router import ModelEndpoint, ModelFactory, ModelProvider
    from langchain_core.messages import HumanMessage

    # 1. Reachability probe
    ds_ok, qwen_ok = False, False
    ds_err, qwen_err = None, None
    ds_model, qwen_model = None, None
    try:
        ds_ep = ModelEndpoint(
            provider=ModelProvider.DEEPSEEK, model_name="deepseek-flash-v4-1017", max_tokens=5
        )
        ds_model = ModelFactory.create_model(ds_ep)
        res_ds = ds_model.invoke([HumanMessage(content="ping")])
        ds_ok = bool(res_ds and res_ds.content is not None)
    except Exception as exc:
        ds_err = str(exc)

    try:
        qwen_ep = ModelEndpoint(
            provider=ModelProvider.QWEN, model_name="qwen2.5-vl-72b-instruct", max_tokens=5
        )
        qwen_model = ModelFactory.create_model(qwen_ep)
        res_qwen = qwen_model.invoke([HumanMessage(content="ping")])
        qwen_ok = bool(res_qwen and res_qwen.content is not None)
    except Exception as exc:
        qwen_err = str(exc)

    if ds_ok and qwen_ok:
        results["probes"]["1_model_reachability"] = {
            "status": "verified",
            "deepseek": {"model": "deepseek-flash-v4-1017", "accessible": True},
            "qwen": {"model": "qwen2.5-vl-72b-instruct", "accessible": True},
        }
    else:
        results["probes"]["1_model_reachability"] = {
            "status": "failed",
            "deepseek": {"model": "deepseek-flash-v4-1017", "accessible": ds_ok, "error": ds_err},
            "qwen": {"model": "qwen2.5-vl-72b-instruct", "accessible": qwen_ok, "error": qwen_err},
        }

    # 2. Multimodal perception probe
    mm_ok = False
    mm_err = None
    if ds_model is not None:
        try:
            png_bytes = _make_dummy_png(64, 64, (255, 0, 0))
            png_b64 = base64.b64encode(png_bytes).decode("utf-8")
            mm_msg = HumanMessage(
                content=[
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{png_b64}"}},
                    {
                        "type": "text",
                        "text": "What is the color of this 64x64 image? Return one word.",
                    },
                ]
            )
            res_mm = ds_model.invoke([mm_msg])
            mm_ok = bool(res_mm and "red" in str(res_mm.content).lower())
        except Exception as exc:
            mm_err = str(exc)
    else:
        mm_err = "Model not constructed"

    results["probes"]["2_multimodal_perception"] = {
        "status": "verified" if mm_ok else "failed",
        "deepseek_image_url": "supported" if mm_ok else "unverified",
        "error": mm_err if not mm_ok else None,
    }

    # 3. Structured output probe
    st_ok = False
    st_err = None
    if ds_model is not None:
        try:

            class PingTag(BaseModel):
                tag: str

            st_m = ds_model.with_structured_output(PingTag, method="function_calling")
            st_res = st_m.invoke([HumanMessage(content="Output tag ping")])
            st_ok = isinstance(st_res, PingTag) and st_res.tag == "ping"
        except Exception as exc:
            st_err = str(exc)
    else:
        st_err = "Model not constructed"

    results["probes"]["3_structured_output"] = {
        "status": "verified" if st_ok else "failed",
        "deepseek_preferred": "function_calling" if st_ok else None,
        "error": st_err if not st_ok else None,
    }

    # 4. Streaming usage probe
    stream_ok = False
    stream_err = None
    if ds_model is not None:
        try:
            chunks = list(ds_model.stream([HumanMessage(content="hi")]))
            stream_ok = any(getattr(c, "usage_metadata", None) is not None for c in chunks)
        except Exception as exc:
            stream_err = str(exc)
    else:
        stream_err = "Model not constructed"

    results["probes"]["4_streaming_usage"] = {
        "status": "verified" if stream_ok else "failed",
        "stream_usage_supported": stream_ok,
        "error": stream_err if not stream_ok else None,
    }

    # 5. Grounding calibration probe (calls object_detector model with synthetic image)
    grounding_ok = False
    norm_center = None
    g_err = None
    try:
        from artemis.agents.object_detector.object_detector import _detect_single_label

        synth_png = _make_synthetic_grounding_png(400, 800, (100, 500, 200, 600))
        qwen_ep = ModelEndpoint(
            provider=ModelProvider.QWEN,
            model_name="qwen2.5-vl-72b-instruct",
            coord_format="bbox_xyxy_px",
        )
        qwen_det = ModelFactory.create_model(qwen_ep)
        coro = _detect_single_label(
            primary_llm=qwen_det,
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
        if det_res and len(det_res) > 0:
            norm_center = det_res[0].get("point")
            if norm_center and abs(norm_center[0] - 375) <= 25 and abs(norm_center[1] - 688) <= 25:
                grounding_ok = True
    except Exception as exc:
        g_err = str(exc)

    results["probes"]["5_grounding_calibration"] = {
        "status": "verified" if grounding_ok else "failed",
        "target_box_px": [100, 500, 200, 600],
        "detected_center_norm": norm_center,
        "calibrated_coord_format": "bbox_xyxy_px",
        "error_within_tolerance": grounding_ok,
        "error": g_err if not grounding_ok else None,
    }

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
