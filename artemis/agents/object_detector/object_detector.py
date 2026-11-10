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

"""Universal Multi-Model Object Detector for Artemis."""

import asyncio
import base64
import json
import os
from pathlib import Path
import re

from langchain_core.messages import HumanMessage, ToolMessage

from artemis.llm.structured import ParseFailure, parse_structured
from artemis.services.llm import get_llm
from third_party.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

_DETECTOR_SEMAPHORE = asyncio.Semaphore(6)


def _clamp_1000(val: float) -> int:
    return max(0, min(1000, int(round(val))))


def normalize_detected_coordinate(
    item: dict,
    *,
    coord_format: str = "point_yx_1000",
    image_size: tuple[int, int] | None = None,
) -> list[int] | None:
    """Normalize raw model detection item into canonical [x, y] in 0..1000.

    Supported coord_format values:
      - 'point_yx_1000': {'point': [y, x]} in 0..1000 (Gemini ER default)
      - 'point_xy_1000': {'point': [x, y]} in 0..1000
      - 'bbox_yxyx_1000': {'box_2d': [ymin, xmin, ymax, xmax]} in 0..1000 (Gemini box)
      - 'bbox_xyxy_1000': {'bbox_2d' | 'box_2d': [xmin, ymin, xmax, ymax]} in 0..1000 (Qwen 0-1000)
      - 'bbox_xyxy_px':   {'bbox_2d' | 'box_2d': [xmin, ymin, xmax, ymax]} in pixel coords (Bailian Qwen2.5-VL)

    Returns [x_norm, y_norm] in [0, 1000], or None if malformed / degenerate.
    """
    if not isinstance(item, dict):
        return None

    # 1. Explicit 2D point
    pt = item.get("point") or item.get("point_2d")
    if isinstance(pt, (list, tuple)) and len(pt) == 2:
        try:
            a, b = float(pt[0]), float(pt[1])
        except (TypeError, ValueError):
            return None
        if coord_format == "point_yx_1000":
            raw_x, raw_y = b, a
        elif coord_format == "bbox_xyxy_px":
            if not image_size or image_size[0] <= 0 or image_size[1] <= 0:
                return None
            raw_x = a / image_size[0] * 1000.0
            raw_y = b / image_size[1] * 1000.0
        else:
            raw_x, raw_y = a, b
        return [_clamp_1000(raw_x), _clamp_1000(raw_y)]

    # 2. 4-element Bounding Box
    box = item.get("bbox_2d") or item.get("box_2d") or item.get("bounding_box")
    if isinstance(box, (list, tuple)) and len(box) == 4:
        try:
            c0, c1, c2, c3 = float(box[0]), float(box[1]), float(box[2]), float(box[3])
        except (TypeError, ValueError):
            return None

        if coord_format == "bbox_yxyx_1000" or (
            coord_format == "point_yx_1000" and "box_2d" in item and "bbox_2d" not in item
        ):
            ymin, xmin, ymax, xmax = c0, c1, c2, c3
        else:
            xmin, ymin, xmax, ymax = c0, c1, c2, c3

        # Reject degenerate or inverted boxes
        if xmax <= xmin or ymax <= ymin:
            return None

        cx = (xmin + xmax) / 2.0
        cy = (ymin + ymax) / 2.0

        if coord_format == "bbox_xyxy_px":
            if not image_size or image_size[0] <= 0 or image_size[1] <= 0:
                return None
            cx = (cx / image_size[0]) * 1000.0
            cy = (cy / image_size[1]) * 1000.0

        return [_clamp_1000(cx), _clamp_1000(cy)]

    return None


def _build_prompt_for_label(
    label: str,
    coord_format: str = "point_yx_1000",
    templates: list[str] | None = None,
) -> str:
    if coord_format in ("bbox_xyxy_px", "bbox_xyxy_1000"):
        template = (
            'Locate "{labels_str}" in the image and return a JSON list of objects with '
            '"bbox_2d": [xmin, ymin, xmax, ymax] and "label": "{labels_str}". Return [] if not found.'
        )
    elif coord_format == "bbox_yxyx_1000":
        template = (
            'Locate "{labels_str}" in the image and return a JSON list of objects with '
            '"box_2d": [ymin, xmin, ymax, xmax] and "label": "{labels_str}". Return [] if not found.'
        )
    elif coord_format == "point_xy_1000":
        template = (
            'Locate "{labels_str}" in the image and return a JSON list of objects with '
            '"point": [x, y] and "label": "{labels_str}". Return [] if not found.'
        )
    elif templates and len(templates) > 0 and "{labels_str}" in templates[0]:
        template = templates[0]
    else:
        template = (
            "Point to the following objects in the provided image: {labels_str}. Return a JSON list of "
            'objects with "point": [y, x] (normalized to 0-1000) and "label": "{labels_str}". Return [] if not found.'
        )
    return template.replace("{labels_str}", label)


async def _detect_single_label(
    primary_llm,
    ctx,
    image_bytes,
    mime_type,
    label,
    *,
    fallback_llm=None,
    primary_coord_format="point_yx_1000",
    fallback_coord_format="point_yx_1000",
    templates=None,
    timeout_val=10.0,
    image_size=None,
    img_b64=None,
) -> list[dict]:
    if img_b64 is None:
        img_b64 = base64.b64encode(image_bytes).decode("utf-8")

    primary_prompt = _build_prompt_for_label(label, primary_coord_format, templates)
    primary_messages = [
        HumanMessage(
            content=[
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{img_b64}"},
                },
                {"type": "text", "text": primary_prompt},
            ]
        )
    ]

    effective_coord_format = primary_coord_format

    async def _invoke_primary():
        nonlocal effective_coord_format
        effective_coord_format = primary_coord_format
        logger.info(f"Calling Object Detector for '{label}' (Attempt 1)...")
        async with _DETECTOR_SEMAPHORE:
            return await asyncio.wait_for(
                primary_llm.ainvoke(primary_messages), timeout=timeout_val
            )

    async def _invoke_fallback():
        nonlocal effective_coord_format
        effective_coord_format = fallback_coord_format
        logger.info(f"Calling Object Detector fallback for '{label}'...")
        fallback_prompt = _build_prompt_for_label(label, fallback_coord_format, templates)
        fallback_messages = [
            HumanMessage(
                content=[
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{img_b64}"},
                    },
                    {"type": "text", "text": fallback_prompt},
                ]
            )
        ]
        async with _DETECTOR_SEMAPHORE:
            return await asyncio.wait_for(
                fallback_llm.ainvoke(fallback_messages), timeout=timeout_val
            )

    response = None
    try:
        if fallback_llm is not None:
            from artemis.services.llm import with_fallback

            response = await with_fallback(_invoke_primary, _invoke_fallback)
        else:
            response = await _invoke_primary()
    except Exception as e:
        logger.warning(f"Detection attempt 1 failed for '{label}': {e}")
        return []

    if response is None:
        return []

    output = response.content if isinstance(response.content, str) else ""
    if isinstance(response.content, list):
        output = "".join(
            b.get("text", "") for b in response.content if isinstance(b, dict) and "text" in b
        )
    logger.info(f"Received response for '{label}'")

    res_json = parse_structured(output)
    if isinstance(res_json, list):
        valid_results = []
        for raw_item in res_json:
            if isinstance(raw_item, dict):
                norm_pt = normalize_detected_coordinate(
                    raw_item,
                    coord_format=effective_coord_format,
                    image_size=image_size,
                )
                if norm_pt is not None:
                    res_item = dict(raw_item)
                    res_item["label"] = label
                    res_item["point"] = norm_pt
                    valid_results.append(res_item)
        return valid_results
    return []


async def _run_object_detection(
    ctx,
    image_bytes: bytes | str | Path | None = None,
    queries: list[str] | None = None,
    templates: list[str] | None = None,
    mime_type: str = "image/jpeg",
    global_timeout: float = 30.0,
    image_path: str | Path | None = None,
) -> dict:
    target_img = image_bytes if image_bytes is not None else image_path
    if target_img is None:
        raise ValueError(
            "Either image_bytes or image_path must be provided to _run_object_detection"
        )
    if isinstance(target_img, (str, Path)):
        image_data = Path(target_img).read_bytes()
    else:
        image_data = target_img

    queries = queries or []

    # Single image encoding and size extraction
    img_b64 = base64.b64encode(image_data).decode("utf-8")
    image_size = None
    try:
        import io
        from PIL import Image

        with Image.open(io.BytesIO(image_data)) as im:
            image_size = im.size
    except Exception:
        image_size = None

    # Resolve primary and fallback LLMs
    try:
        primary_llm = get_llm(ctx, name="object_detector", is_utils=True)
    except Exception:
        primary_llm = get_llm(ctx, name="operator")

    fallback_llm = None
    try:
        fallback_llm = get_llm(ctx, name="object_detector", is_utils=True, use_fallback=True)
    except Exception:
        fallback_llm = None

    # Resolve coord_formats
    detector_cfg = None
    if hasattr(ctx, "llm_config") and hasattr(ctx.llm_config, "get_utils"):
        try:
            detector_cfg = ctx.llm_config.get_utils("object_detector")
        except Exception:
            detector_cfg = None

    primary_coord_format = getattr(getattr(primary_llm, "endpoint", None), "coord_format", None)
    if not primary_coord_format and detector_cfg:
        primary_coord_format = getattr(detector_cfg, "coord_format", None)
    if not primary_coord_format:
        primary_coord_format = "point_yx_1000"

    fallback_coord_format = getattr(getattr(fallback_llm, "endpoint", None), "coord_format", None)
    if not fallback_coord_format and detector_cfg:
        fb_cfg = getattr(detector_cfg, "fallback", None)
        if fb_cfg:
            fallback_coord_format = getattr(fb_cfg, "coord_format", None)
    if not fallback_coord_format:
        fallback_coord_format = primary_coord_format

    # Resolve timeout
    if detector_cfg and getattr(detector_cfg, "timeout", None) is not None:
        timeout_val = float(detector_cfg.timeout)
    elif os.environ.get("OBJECT_DETECTOR_TIMEOUT"):
        timeout_val = float(os.environ["OBJECT_DETECTOR_TIMEOUT"])
    elif hasattr(ctx, "llm_config") and getattr(ctx.llm_config, "timeout", None) is not None:
        timeout_val = float(ctx.llm_config.timeout)
    else:
        timeout_val = 10.0

    tasks = [
        asyncio.create_task(
            _detect_single_label(
                primary_llm,
                ctx,
                image_data,
                mime_type,
                label=query,
                fallback_llm=fallback_llm,
                primary_coord_format=primary_coord_format,
                fallback_coord_format=fallback_coord_format,
                templates=templates,
                timeout_val=timeout_val,
                image_size=image_size,
                img_b64=img_b64,
            )
        )
        for query in queries
    ]

    done, pending = await asyncio.wait(tasks, timeout=global_timeout)

    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)

    fused_results = []
    for task in done:
        try:
            res = task.result()
            if res:
                fused_results.extend(res)
        except Exception as e:
            logger.error(f"Task raised exception: {e}")

    detected_labels = set(
        item["label"] for item in fused_results if isinstance(item, dict) and "label" in item
    )
    failed_queries = [query for query in queries if query not in detected_labels]

    result_dict = {"detected": fused_results, "failed": failed_queries}

    if failed_queries:
        result_dict["message"] = (
            "Detection failed for some targets. Please try changing to a more"
            " detailed description (e.g., describe its shape, color, or nearby"
            " text)."
        )

    logger.info("Fused results from parallel inference.")
    return result_dict


async def _create_error_command(ctx, state, tool_call_id, error_message, wrapper):
    return ToolMessage(
        tool_call_id=tool_call_id or "default_tool_call",
        content=wrapper.on_failure_fn(error_message),
        additional_kwargs={"error": error_message},
        status="error",
    )


async def _create_success_command(ctx, state, tool_call_id, output, wrapper):
    return ToolMessage(
        tool_call_id=tool_call_id or "default_tool_call",
        content=wrapper.on_success_fn(output),
        status="success",
    )
