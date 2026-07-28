from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from wakeword import (
    AdaptiveInferenceScheduler,
    AudioWindow,
    LatestWindowWorker,
    LiveKitWakeBackend,
    WakeActivityGate,
    WakeScorePolicy,
    build_cpu_predictor,
)


def test_audio_window_starts_zero_filled() -> None:
    window = AudioWindow(32_000)

    snapshot = window.snapshot()

    assert snapshot.shape == (32_000,)
    assert snapshot.dtype == np.int16
    assert np.count_nonzero(snapshot) == 0
    assert window.real_sample_count == 0


def test_audio_window_replaces_oldest_samples() -> None:
    window = AudioWindow(8)
    first = np.array([1, 2, 3], dtype=np.int16)
    second = np.array([4, 5, 6, 7, 8, 9], dtype=np.int16)

    window.append(first)
    window.append(second)

    assert window.real_sample_count == 8
    np.testing.assert_array_equal(
        window.snapshot(),
        np.array([2, 3, 4, 5, 6, 7, 8, 9], dtype=np.int16),
    )


def test_audio_window_owns_appended_memory() -> None:
    window = AudioWindow(4)
    source = np.array([1, 2, 3, 4], dtype=np.int16)
    window.append(source)
    source[:] = 9

    np.testing.assert_array_equal(
        window.snapshot(),
        np.array([1, 2, 3, 4], dtype=np.int16),
    )


def test_wake_activity_gate_uses_rms_when_vad_misses_speech() -> None:
    gate = WakeActivityGate(-50.0)
    quiet = np.full(1_280, 4, dtype=np.int16)
    voice_level = np.full(1_280, 256, dtype=np.int16)

    quiet_active, quiet_dbfs = gate.is_active(quiet, vad_speech=False)
    voice_active, voice_dbfs = gate.is_active(voice_level, vad_speech=False)

    assert not quiet_active
    assert quiet_dbfs < -50.0
    assert voice_active
    assert voice_dbfs >= -50.0


def test_wake_activity_gate_honors_vad_at_low_rms() -> None:
    gate = WakeActivityGate(-50.0)

    active, _ = gate.is_active(
        np.zeros(1_280, dtype=np.int16),
        vad_speech=True,
    )

    assert active


def test_wake_score_policy_detects_three_early_candidates() -> None:
    policy = WakeScorePolicy(
        threshold=0.6,
        early_threshold=0.15,
        early_consecutive=3,
    )

    first = policy.observe(0.16)
    second = policy.observe(0.18)
    third = policy.observe(0.17)

    assert not first.detected
    assert first.early_count == 1
    assert not second.detected
    assert second.early_count == 2
    assert third.detected
    assert third.trigger == "early"
    assert third.effective_threshold == 0.15


def test_wake_score_policy_resets_early_sequence_on_low_score() -> None:
    policy = WakeScorePolicy(
        threshold=0.6,
        early_threshold=0.15,
        early_consecutive=3,
    )

    policy.observe(0.2)
    policy.observe(0.1)
    decision = policy.observe(0.2)

    assert not decision.detected
    assert decision.early_count == 1


def test_wake_score_policy_keeps_normal_threshold_immediate() -> None:
    policy = WakeScorePolicy(
        threshold=0.6,
        early_threshold=0.15,
        early_consecutive=3,
    )

    decision = policy.observe(0.8)

    assert decision.detected
    assert decision.trigger == "normal"
    assert decision.effective_threshold == 0.6


def test_scheduler_supports_zero_and_nonzero_warmup() -> None:
    immediate = AdaptiveInferenceScheduler(
        active_interval_sec=0.16,
        idle_interval_sec=1.0,
        speech_hold_sec=2.0,
        warmup_samples=0,
    )
    delayed = AdaptiveInferenceScheduler(
        active_interval_sec=0.16,
        idle_interval_sec=1.0,
        speech_hold_sec=2.0,
        warmup_samples=16_000,
    )

    assert immediate.should_request(
        now=1.0,
        has_speech=False,
        real_sample_count=1_280,
    )
    assert not delayed.should_request(
        now=1.0,
        has_speech=False,
        real_sample_count=15_999,
    )
    assert delayed.should_request(
        now=1.1,
        has_speech=False,
        real_sample_count=16_000,
    )


def test_scheduler_requests_immediately_on_speech_start() -> None:
    scheduler = AdaptiveInferenceScheduler(
        active_interval_sec=0.16,
        idle_interval_sec=1.0,
        speech_hold_sec=2.0,
        warmup_samples=0,
    )
    assert scheduler.should_request(
        now=1.0,
        has_speech=False,
        real_sample_count=1_280,
    )
    assert scheduler.should_request(
        now=1.01,
        has_speech=True,
        real_sample_count=2_560,
    )


def test_latest_window_worker_replaces_pending_request() -> None:
    started = threading.Event()
    release = threading.Event()

    def predictor(audio: np.ndarray) -> dict[str, float]:
        started.set()
        release.wait(timeout=1.0)
        return {"wake": float(audio[-1])}

    worker = LatestWindowWorker(predictor)
    try:
        worker.submit(np.array([1], dtype=np.int16), generation=0, captured_at=1.0)
        assert started.wait(timeout=1.0)
        worker.submit(np.array([2], dtype=np.int16), generation=0, captured_at=2.0)
        worker.submit(np.array([3], dtype=np.int16), generation=0, captured_at=3.0)
        assert worker.dropped_count == 1
        release.set()
        deadline = time.monotonic() + 1.0
        latest = None
        while time.monotonic() < deadline:
            result = worker.poll()
            if result is not None and result.captured_at == 3.0:
                latest = result
                break
            threading.Event().wait(0.01)
        assert latest is not None
        assert latest.scores["wake"] == 3.0
        assert worker.completed_count == 2
    finally:
        worker.close()


def test_livekit_backend_detects_threshold_hit() -> None:
    predicted = threading.Event()

    def predictor(audio: np.ndarray) -> dict[str, float]:
        assert audio.shape == (32_000,)
        predicted.set()
        return {"nee_yatagarasu": 0.8}

    backend = LiveKitWakeBackend(
        model_path=None,  # type: ignore[arg-type]
        threshold=0.6,
        debounce_sec=2.0,
        active_interval_sec=0.16,
        idle_interval_sec=1.0,
        speech_hold_sec=2.0,
        warmup_sec=0.0,
        predictor=predictor,
    )
    try:
        backend.feed_audio(
            np.ones(1_280, dtype=np.int16),
            has_speech=True,
            now=1.0,
        )
        assert predicted.wait(timeout=1.0)
        deadline = time.monotonic() + 1.0
        detection = None
        while time.monotonic() < deadline and detection is None:
            detection = backend.poll(now=1.1)
            threading.Event().wait(0.01)
        assert detection is not None
        assert detection.model_name == "nee_yatagarasu"
        assert detection.score == 0.8
        assert backend.inference_count == 1
        assert backend.dropped_count == 0
    finally:
        backend.close()


def test_cpu_predictor_uses_single_thread_sessions() -> None:
    model_path = (
        Path(__file__).resolve().parents[2]
        / "models"
        / "wakeword"
        / "nee_yatagarasu.onnx"
    )
    predictor = build_cpu_predictor(model_path)
    model = predictor.__self__

    scores = predictor(np.zeros(32_000, dtype=np.int16))

    assert 0.0 <= scores["nee_yatagarasu"] <= 1.0
    sessions = [
        model._mel_frontend._onnx_session,
        model._speech_embedding._session,
        next(iter(model._classifiers.values()))[0],
    ]
    for session in sessions:
        options = session.get_session_options()
        assert options.intra_op_num_threads == 1
        assert options.inter_op_num_threads == 1
