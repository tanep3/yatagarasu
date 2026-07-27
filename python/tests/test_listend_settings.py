from __future__ import annotations

from pathlib import Path

import pytest

from listend import ListendSettings


WAKE_ENV_NAMES = (
    "LISTEND_RTSP_LOW_LATENCY",
    "LISTEND_WAKE_BACKEND",
    "LISTEND_WAKE_MODEL_PATH",
    "LISTEND_WAKE_THRESHOLD",
    "LISTEND_WAKE_EARLY_THRESHOLD",
    "LISTEND_WAKE_EARLY_CONSECUTIVE",
    "LISTEND_WAKE_DEBOUNCE_SEC",
    "LISTEND_WAKE_ACTIVE_INTERVAL_SEC",
    "LISTEND_WAKE_IDLE_INTERVAL_SEC",
    "LISTEND_WAKE_ACTIVITY_RMS_DBFS",
    "LISTEND_WAKE_SPEECH_HOLD_SEC",
    "LISTEND_WAKE_WARMUP_SEC",
    "LISTEND_WAKE_PROMPT_AUDIO",
    "LISTEND_WAKE_PROMPT_GUARD_SEC",
    "LISTEND_WAKE_PROMPT_TIMEOUT_SEC",
)


def configure_minimal_env(monkeypatch, tmp_path: Path) -> Path:
    project_root = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    for name in WAKE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("YATAGARASU_CWD", str(workspace))
    monkeypatch.setenv("LISTEND_RTSP_URL", "rtsp://localhost:8554/camera")
    monkeypatch.setenv("LISTEND_WAKE_WORDS", "ねぇ、ヤタガラス")
    monkeypatch.setenv("LISTEND_STOP_WORDS", "ストップ")
    monkeypatch.setenv(
        "LISTEND_WAKE_MODEL_PATH",
        str(project_root / "models" / "wakeword" / "nee_yatagarasu.onnx"),
    )
    monkeypatch.setenv(
        "LISTEND_WAKE_PROMPT_AUDIO",
        str(project_root / "assets" / "audio" / "wake_prompt_hai.mp3"),
    )
    return workspace


def test_livekit_is_default_backend(monkeypatch, tmp_path: Path) -> None:
    configure_minimal_env(monkeypatch, tmp_path)

    settings = ListendSettings.from_env()

    assert settings.wake.backend == "livekit"
    assert settings.rtsp_low_latency
    assert settings.wake.active_interval_sec == 0.08
    assert settings.wake.early_threshold == 0.15
    assert settings.wake.early_consecutive == 3
    assert settings.wake.activity_rms_dbfs == -50.0
    assert settings.wake.warmup_sec == 0.0
    assert settings.wake.prompt_guard_sec == 0.6
    assert settings.wake.prompt_timeout_sec == 2.0
    assert settings.silence_timeout_sec == 3.0
    assert settings.wake_ack_speaker_id == "13"


def test_stt_backend_does_not_require_onnx_assets(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configure_minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("LISTEND_WAKE_BACKEND", "stt")
    monkeypatch.setenv("LISTEND_WAKE_MODEL_PATH", str(tmp_path / "missing.onnx"))
    monkeypatch.setenv("LISTEND_WAKE_PROMPT_AUDIO", str(tmp_path / "missing.mp3"))

    settings = ListendSettings.from_env()

    assert settings.wake.backend == "stt"


def test_warmup_rejects_values_over_two_seconds(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configure_minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("LISTEND_WAKE_WARMUP_SEC", "2.1")

    with pytest.raises(ValueError, match="LISTEND_WAKE_WARMUP_SEC"):
        ListendSettings.from_env()


def test_early_threshold_must_not_exceed_normal_threshold(
    monkeypatch,
    tmp_path: Path,
) -> None:
    configure_minimal_env(monkeypatch, tmp_path)
    monkeypatch.setenv("LISTEND_WAKE_THRESHOLD", "0.6")
    monkeypatch.setenv("LISTEND_WAKE_EARLY_THRESHOLD", "0.7")

    with pytest.raises(ValueError, match="LISTEND_WAKE_EARLY_THRESHOLD"):
        ListendSettings.from_env()
