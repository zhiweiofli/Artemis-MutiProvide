"""S0-L1: recording is opt-in, bounded, and never outlives its task."""

from pathlib import Path
from unittest.mock import patch

from artemis.config import load_agent_config
from artemis.runtime import orphan_recordings
from artemis.utils.video import (
    ANDROID_RECORDING_SEGMENT_SECONDS,
    MAX_RECORDING_SESSION_SECONDS,
    SCRCPY_SEGMENT_TIME_LIMIT_SECONDS,
    build_scrcpy_record_command,
)


def test_recording_is_off_by_default_in_both_profiles():
    cfg = load_agent_config()
    assert cfg.video_analyzer.enabled is False
    assert cfg.pro.video_analyzer.enabled is False


def test_segment_command_carries_a_hard_time_limit(tmp_path: Path):
    command = build_scrcpy_record_command(
        "scrcpy", "device-1", tmp_path / "a.mkv", time_limit_s=SCRCPY_SEGMENT_TIME_LIMIT_SECONDS
    )
    assert f"--time-limit={SCRCPY_SEGMENT_TIME_LIMIT_SECONDS}" in command
    # The default stays without a limit so other callers are unaffected.
    assert "--time-limit=" not in " ".join(
        build_scrcpy_record_command("scrcpy", "device-1", tmp_path / "b.mkv")
    )


def test_session_cap_is_finite_and_bounded():
    assert MAX_RECORDING_SESSION_SECONDS > ANDROID_RECORDING_SEGMENT_SECONDS
    assert MAX_RECORDING_SESSION_SECONDS <= 3 * ANDROID_RECORDING_SEGMENT_SECONDS


def test_orphaned_recorder_is_killed_but_owned_ones_are_left_alone():
    ps_output = (
        "  PID  PPID COMMAND\n"
        "  111     1 scrcpy --serial 89FX09M9U --no-window --record /tmp/a.mkv\n"
        "  222   999 scrcpy --serial 89FX09M9U --no-window --record /tmp/live.mkv\n"
        "  333     1 scrcpy --serial OTHER --no-window --record /tmp/b.mkv\n"
        "  444     1 ffmpeg -i /tmp/a.mkv out.mp4\n"
    )
    with (
        patch.object(orphan_recordings.subprocess, "run") as run,
        patch.object(orphan_recordings.os, "kill") as kill,
    ):
        run.return_value.stdout = ps_output
        run.return_value.returncode = 0
        killed = orphan_recordings.reap_orphan_recordings("89FX09M9U", adb_command=lambda args: "")

    assert killed == [111]
    kill.assert_called_once()
