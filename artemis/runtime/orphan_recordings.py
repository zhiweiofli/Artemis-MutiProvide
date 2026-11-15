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

"""Reap recording processes whose owning task is gone (S0-L1).

A killed task used to leave its recorder behind and keep writing: two
``recording.mkv`` files reached 8.7 GiB, last written ~10 hours after the run.
The host-side scrcpy is the one that keeps growing (it writes the host file),
so both halves are cleaned here: orphaned host scrcpy processes (parent is
init) and stale device-side ``screenrecord`` processes.
"""

from __future__ import annotations

import os
import signal
import subprocess

from third_party.mobile_use.utils.logger import get_logger

logger = get_logger(__name__)


def _host_orphan_scrcpy_pids(device_id: str | None) -> list[int]:
    """scrcpy processes recording this device that nobody owns any more."""
    try:
        completed = subprocess.run(
            ["ps", "-axo", "pid,ppid,command"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.debug(f"Could not list processes for the orphan sweep: {e}")
        return []

    pids: list[int] = []
    for line in completed.stdout.splitlines()[1:]:
        parts = line.split(None, 2)
        if len(parts) != 3:
            continue
        pid_text, ppid_text, command = parts
        if "--record" not in command or "scrcpy" not in command:
            continue
        if device_id and f"--serial {device_id}" not in command and f"-s {device_id}" not in command:
            continue
        # ppid 1 / launchd: the task that started it is gone.
        if ppid_text.strip() not in ("1", "0"):
            continue
        if not pid_text.isdigit():
            continue
        pids.append(int(pid_text))
    return pids


def reap_orphan_recordings(device_id: str | None = None, adb_command=None) -> list[int]:
    """Kill orphaned recorders; returns the host PIDs that were signalled.

    ``adb_command`` is an optional ``(args) -> str`` callable so the device-side
    sweep can reuse the caller's own ADB wiring (and stay testable).
    """
    killed: list[int] = []
    for pid in _host_orphan_scrcpy_pids(device_id):
        try:
            os.kill(pid, signal.SIGKILL)
            killed.append(pid)
            logger.warning(f"Killed orphaned scrcpy recorder pid={pid} (no owning task).")
        except ProcessLookupError:
            continue
        except OSError as e:
            logger.debug(f"Could not kill orphaned scrcpy pid={pid}: {e}")

    if device_id:
        try:
            if adb_command is not None:
                adb_command(["-s", device_id, "shell", "pkill", "-f", "screenrecord"])
            else:
                subprocess.run(
                    ["adb", "-s", device_id, "shell", "pkill", "-f", "screenrecord"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
        except (OSError, subprocess.SubprocessError) as e:
            logger.debug(f"Device-side screenrecord sweep skipped: {e}")

    return killed
