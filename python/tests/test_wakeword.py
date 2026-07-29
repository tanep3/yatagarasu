from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np

from wakeword import (
    AdaptiveInferenceScheduler,
    AudioWindow,
    InferenceResult,
    IncrementalWakePredictor,
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
    model = predictor.model

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


def test_incremental_predictor_reuses_overlapping_embeddings_without_score_drift(
) -> None:
    model_path = (
        Path(__file__).resolve().parents[2]
        / "models"
        / "wakeword"
        / "nee_yatagarasu.onnx"
    )
    predictor = build_cpu_predictor(model_path)
    reference = predictor.model.predict
    random = np.random.default_rng(7)
    stream = random.integers(
        np.iinfo(np.int16).min,
        np.iinfo(np.int16).max,
        size=34_560,
        dtype=np.int16,
    )
    windows = (
        stream[0:32_000],
        stream[1_280:33_280],
        stream[2_560:34_560],
    )

    for window in windows:
        expected = reference(window)
        actual = predictor(window)
        assert actual.keys() == expected.keys()
        for model_name, score in expected.items():
            assert actual[model_name] == score

    assert predictor.cache_misses == 1
    assert predictor.cache_hits == 2


def test_incremental_predictor_falls_back_for_discontinuous_audio() -> None:
    class FakeFrontend:
        def __call__(self, audio: np.ndarray) -> np.ndarray:
            return np.zeros((1, 197, 32), dtype=np.float32)

    class FakeEmbedding:
        def __call__(self, window: np.ndarray) -> np.ndarray:
            return np.zeros((1, 96), dtype=np.float32)

    class FakeSession:
        def run(
            self,
            _outputs: object,
            _inputs: dict[str, np.ndarray],
        ) -> list[np.ndarray]:
            return [np.array([[0.5]], dtype=np.float32)]

    class FakeModel:
        _mel_frontend = FakeFrontend()
        _speech_embedding = FakeEmbedding()
        _classifiers = {"wake": (FakeSession(), "embeddings")}

    predictor = IncrementalWakePredictor(FakeModel())

    assert predictor(np.zeros(32_000, dtype=np.int16))["wake"] == 0.5
    assert predictor(np.ones(32_000, dtype=np.int16))["wake"] == 0.5
    assert predictor.cache_hits == 0
    assert predictor.cache_misses == 2


def test_silence_lookahead_shifts_audio_without_mutating_cache() -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.received: np.ndarray | None = None

        def predict(self, audio: np.ndarray) -> dict[str, float]:
            self.received = audio.copy()
            return {"wake": 0.75}

    model = FakeModel()
    predictor = IncrementalWakePredictor(model)
    audio = np.arange(10, dtype=np.int16)

    scores = predictor.predict_silence_lookahead(audio, 3)

    assert scores == {"wake": 0.75}
    assert model.received is not None
    np.testing.assert_array_equal(
        model.received,
        np.array([3, 4, 5, 6, 7, 8, 9, 0, 0, 0], dtype=np.int16),
    )
    assert predictor.cache_hits == 0
    assert predictor.cache_misses == 0


def test_shadow_lookahead_runs_once_after_configured_silence() -> None:
    backend = LiveKitWakeBackend(
        model_path=None,  # type: ignore[arg-type]
        threshold=0.65,
        debounce_sec=2.0,
        active_interval_sec=0.08,
        idle_interval_sec=1.5,
        speech_hold_sec=2.0,
        warmup_sec=0.0,
        lookahead_mode="shadow",
        lookahead_target_sec=1.16,
        lookahead_silence_chunks=2,
        predictor=lambda audio: {"wake": 0.0},
    )
    try:
        assert backend._observe_lookahead_activity(True, 1.0) == 0
        assert backend._observe_lookahead_activity(False, 1.08) == 0
        assert backend._observe_lookahead_activity(False, 1.16) == 16_000
        assert backend._observe_lookahead_activity(False, 1.24) == 0
    finally:
        backend.close()


def test_shadow_lookahead_compares_virtual_score_with_real_future(
    caplog,
) -> None:
    backend = LiveKitWakeBackend(
        model_path=None,  # type: ignore[arg-type]
        threshold=0.65,
        debounce_sec=2.0,
        active_interval_sec=0.08,
        idle_interval_sec=1.5,
        speech_hold_sec=2.0,
        warmup_sec=0.0,
        lookahead_mode="shadow",
        predictor=lambda audio: {"wake": 0.0},
    )
    try:
        probe_result = InferenceResult(
            generation=0,
            captured_at=1.0,
            completed_at=1.1,
            scores={"wake": 0.1},
            lookahead_scores={"wake": 0.6},
            elapsed_sec=0.1,
            lookahead_silence_samples=16_000,
        )
        backend._observe_lookahead_result(probe_result, "wake", 0.1)
        assert backend._lookahead_probe is not None
        assert backend._lookahead_probe.target_at == 2.0

        before_target = InferenceResult(
            generation=0,
            captured_at=1.9,
            completed_at=1.91,
            scores={"wake": 0.55},
            lookahead_scores={},
            elapsed_sec=0.01,
        )
        backend._observe_lookahead_result(before_target, "wake", 0.55)
        assert backend._lookahead_probe is not None

        future_result = InferenceResult(
            generation=0,
            captured_at=2.03,
            completed_at=2.04,
            scores={"wake": 0.58},
            lookahead_scores={},
            elapsed_sec=0.01,
        )
        with caplog.at_level("INFO"):
            backend._observe_lookahead_result(future_result, "wake", 0.58)

        assert backend._lookahead_probe is None
        assert "outcome=target_reached" in caplog.text
        assert "virtual_score=0.6000" in caplog.text
        assert "future_score=0.5800" in caplog.text
        assert "target_lag_ms=30.0" in caplog.text
    finally:
        backend.close()


def test_lookahead_fills_remaining_two_second_window() -> None:
    backend = LiveKitWakeBackend(
        model_path=None,  # type: ignore[arg-type]
        threshold=0.65,
        debounce_sec=2.0,
        active_interval_sec=0.08,
        idle_interval_sec=1.5,
        speech_hold_sec=2.0,
        warmup_sec=0.0,
        lookahead_mode="active",
        lookahead_target_sec=2.0,
        lookahead_max_silence_sec=1.5,
        predictor=lambda audio: {"wake": 0.0},
    )
    try:
        assert backend._observe_lookahead_activity(True, 10.0) == 0
        assert backend._lookahead_samples_at(10.5) == 24_000
        assert backend._lookahead_samples_at(11.77) == 3_680
        assert backend._lookahead_samples_at(11.95) == 0
    finally:
        backend.close()


def test_lookahead_uses_audio_samples_instead_of_wall_time() -> None:
    backend = LiveKitWakeBackend(
        model_path=None,  # type: ignore[arg-type]
        threshold=0.65,
        debounce_sec=2.0,
        active_interval_sec=0.08,
        idle_interval_sec=1.5,
        speech_hold_sec=2.0,
        warmup_sec=0.0,
        lookahead_mode="active",
        lookahead_target_sec=2.0,
        lookahead_max_silence_sec=2.0,
        lookahead_silence_chunks=2,
        predictor=lambda audio: {"wake": 0.0},
    )
    try:
        assert backend._observe_lookahead_activity(
            True,
            10.0,
            sample_count=8_000,
        ) == 0
        assert backend._observe_lookahead_activity(
            False,
            10.9,
            sample_count=1_280,
        ) == 0
        assert backend._observe_lookahead_activity(
            False,
            11.8,
            sample_count=1_280,
        ) == 21_440
    finally:
        backend.close()


def test_pending_lookahead_is_not_replaced_by_normal_inference() -> None:
    def result(
        captured_at: float,
        silence_samples: int,
        generation: int = 0,
    ) -> InferenceResult:
        return InferenceResult(
            generation=generation,
            captured_at=captured_at,
            completed_at=captured_at + 0.01,
            scores={"wake": 0.0},
            lookahead_scores={},
            elapsed_sec=0.01,
            lookahead_silence_samples=silence_samples,
        )

    existing = result(1.0, 16_000)
    normal = result(1.1, 0)
    newer_lookahead = result(1.2, 12_800)

    assert not LatestWindowWorker._can_replace(existing, normal)
    assert LatestWindowWorker._can_replace(existing, newer_lookahead)
    assert LatestWindowWorker._can_replace(normal, newer_lookahead)
    assert LatestWindowWorker._can_replace(existing, result(1.3, 0, 1))


def test_active_lookahead_detects_at_normal_threshold() -> None:
    backend = LiveKitWakeBackend(
        model_path=None,  # type: ignore[arg-type]
        threshold=0.65,
        debounce_sec=2.0,
        active_interval_sec=0.08,
        idle_interval_sec=1.5,
        speech_hold_sec=2.0,
        warmup_sec=0.0,
        lookahead_mode="active",
        lookahead_trigger_score=0.10,
        lookahead_threshold=0.55,
        predictor=lambda audio: {"wake": 0.0},
    )
    result = InferenceResult(
        generation=0,
        captured_at=1.0,
        completed_at=1.06,
        scores={"wake": 0.1},
        lookahead_scores={"wake": 0.75},
        elapsed_sec=0.06,
    )
    try:
        with backend._worker._condition:
            backend._worker._result = result

        detection = backend.poll(now=1.07)

        assert detection is not None
        assert detection.trigger == "lookahead"
        assert detection.score == 0.75
        assert detection.threshold == 0.55
        assert detection.detected_at == 1.0
        assert detection.lookahead_probe_score == 0.75
    finally:
        backend.close()


def test_active_lookahead_requires_both_scores() -> None:
    backend = LiveKitWakeBackend(
        model_path=None,  # type: ignore[arg-type]
        threshold=0.65,
        debounce_sec=2.0,
        active_interval_sec=0.08,
        idle_interval_sec=1.5,
        speech_hold_sec=2.0,
        warmup_sec=0.0,
        lookahead_mode="active",
        lookahead_trigger_score=0.10,
        lookahead_threshold=0.55,
        predictor=lambda audio: {"wake": 0.0},
    )
    result = InferenceResult(
        generation=0,
        captured_at=1.0,
        completed_at=1.06,
        scores={"wake": 0.09},
        lookahead_scores={"wake": 0.64},
        elapsed_sec=0.06,
    )
    try:
        with backend._worker._condition:
            backend._worker._result = result

        assert backend.poll(now=1.07) is None
    finally:
        backend.close()


def test_vad_lookahead_uses_completed_window_score_without_current_guard() -> None:
    backend = LiveKitWakeBackend(
        model_path=None,  # type: ignore[arg-type]
        threshold=0.65,
        debounce_sec=2.0,
        active_interval_sec=0.08,
        idle_interval_sec=1.5,
        speech_hold_sec=2.0,
        warmup_sec=0.0,
        lookahead_mode="active",
        lookahead_trigger_score=0.10,
        lookahead_threshold=0.55,
        predictor=lambda audio: {"wake": 0.0},
    )
    result = InferenceResult(
        generation=0,
        captured_at=1.0,
        completed_at=1.06,
        scores={"wake": 0.05},
        lookahead_scores={"wake": 0.75},
        elapsed_sec=0.06,
        lookahead_silence_samples=16_000,
        lookahead_source="vad",
    )
    try:
        with backend._worker._condition:
            backend._worker._result = result

        detection = backend.poll(now=1.07)

        assert detection is not None
        assert detection.trigger == "lookahead"
        assert detection.score == 0.75
    finally:
        backend.close()


def test_active_lookahead_requests_probe_when_score_starts_rising() -> None:
    backend = LiveKitWakeBackend(
        model_path=None,  # type: ignore[arg-type]
        threshold=0.65,
        debounce_sec=2.0,
        active_interval_sec=0.08,
        idle_interval_sec=1.5,
        speech_hold_sec=2.0,
        warmup_sec=0.0,
        lookahead_mode="active",
        lookahead_trigger_score=0.10,
        lookahead_threshold=0.55,
        predictor=lambda audio: {"wake": 0.0},
    )
    submitted: list[dict[str, object]] = []

    def capture_submit(_audio: np.ndarray, **kwargs: object) -> None:
        submitted.append(kwargs)

    backend._worker.submit = capture_submit  # type: ignore[method-assign]
    result = InferenceResult(
        generation=0,
        captured_at=1.0,
        completed_at=1.01,
        scores={"wake": 0.12},
        lookahead_scores={},
        elapsed_sec=0.01,
    )
    try:
        backend._observe_lookahead_activity(True, 0.0)
        backend._request_score_lookahead(result, 0.12, 1.0)
        backend._request_score_lookahead(result, 0.20, 1.1)
        backend._request_score_lookahead(result, 0.20, 1.3)

        assert len(submitted) == 2
        assert submitted[0]["lookahead_silence_samples"] == 16_000
        assert submitted[0]["captured_at"] == 1.0
        assert submitted[1]["lookahead_silence_samples"] == 11_200
        assert submitted[1]["captured_at"] == 1.3
    finally:
        backend.close()
