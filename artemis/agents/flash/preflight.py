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

"""Stage-boundary foreground check for the Flash runner (S0-C3).

A previous game's screen can still be up when a new task starts: session
``019828f8`` launched 斗破, photographed 大圣's loading screen, wrote that title
into the report and failed 22 seconds in. The check below runs before the first
frame is captured, so a stale screen can never enter the model's context.

The expected package comes from the task's app lock (``--locked-app``): the SDK
already launches it and checks the foreground (``_handle_initial_app_launch``),
but only logs when that fails. Without a lock there is nothing to compare
against and the check is a no-op.
"""

from __future__ import annotations

import asyncio
import time

from artemis.context import ArtemisContext
from artemis.utils.app_launch_utils import observe_foreground
from third_party.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)

#: One relaunch attempt, then a bounded wait for the window to settle.
_RETRY_SETTLE_SECONDS = 2.0
_FOREGROUND_POLL_SECONDS = 10.0
_FOREGROUND_POLL_INTERVAL = 0.5


def expected_package(ctx: ArtemisContext) -> str | None:
    """The package the task is locked to, or ``None`` when the task is unlocked."""
    setup = getattr(ctx, "execution_setup", None)
    getter = getattr(setup, "get_locked_app_package", None)
    package: object = None
    if callable(getter):
        try:
            package = getter()
        except Exception:  # pragma: no cover - defensive, setup is optional
            return None
    # Only a real package name counts: a Mock setup (tests, partial wiring)
    # must never make the check think a lock exists.
    return package if isinstance(package, str) and package.strip() else None


async def _wait_for_foreground(ctx: ArtemisContext, package: str) -> tuple[bool, str | None]:
    """Poll the foreground for a bounded time; returns (matched, seen_package)."""
    deadline = time.monotonic() + _FOREGROUND_POLL_SECONDS
    seen: str | None = None
    while True:
        matched, seen, _ = await observe_foreground(ctx, package)
        if matched:
            return True, seen
        if time.monotonic() >= deadline:
            return False, seen
        await asyncio.sleep(_FOREGROUND_POLL_INTERVAL)


async def ensure_foreground(
    ctx: ArtemisContext,
    *,
    launch,
) -> tuple[bool, str | None, str | None]:
    """Verify the locked package owns the screen before the first frame.

    ``launch`` is an awaitable factory (``async def``) used for the single
    relaunch attempt; it keeps this module free of driver imports.

    Returns ``(ok, reason, seen_package)``. ``ok`` is False only when a package
    was expected and never became the foreground app.
    """
    package = expected_package(ctx)
    if not package:
        logger.info("No app lock on this task; skipping the foreground check.")
        return True, None, None

    matched, seen = await _wait_for_foreground(ctx, package)
    if matched:
        logger.info(f"Foreground check passed: '{seen}' owns the screen for task app '{package}'.")
        return True, None, seen

    logger.warning(
        f"Foreground check: expected '{package}', found '{seen}'. Relaunching once before giving up."
    )
    await asyncio.sleep(_RETRY_SETTLE_SECONDS)
    try:
        await launch(package)
    except Exception as e:  # pragma: no cover - relaunch failure is reported, not raised
        logger.warning(f"Foreground check relaunch raised: {e}")

    matched, seen = await _wait_for_foreground(ctx, package)
    if matched:
        logger.info(f"Foreground check passed after relaunch: '{seen}'.")
        return True, None, seen

    reason = (
        f"Foreground package mismatch: expected '{package}', "
        f"screen shows '{seen or 'unknown'}' after one relaunch attempt."
    )
    return False, reason, seen
