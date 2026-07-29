from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

import numpy as np
from numpy.typing import NDArray


Int16Array = NDArray[np.int16]
ScoreMap = Mapping[str, float]
Predictor = Callable[[Int16Array], ScoreMap]
EMBEDDING_STEP_SAMPLES = 1_280


class WakeActivityGate:
    def __init__(self, rms_threshold_dbfs: float) -> None:
        if not -120.0 <= rms_threshold_dbfs <= 0.0:
            raise ValueError("rms_threshold_dbfs must be between -120 and 0")
        self._rms_threshold_dbfs = rms_threshold_dbfs

    @property
    def rms_threshold_dbfs(self) -> float:
        return self._rms_threshold_dbfs

    def is_active(self, pcm: Int16Array, *, vad_speech: bool) -> tuple[bool, float]:
        samples = np.asarray(pcm, dtype=np.int16).reshape(-1)
        if samples.size == 0:
            return vad_speech, -120.0
        audio = samples.astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(np.square(audio))))
        rms_dbfs = -120.0 if rms <= 1e-9 else 20.0 * np.log10(rms)
        return vad_speech or rms_dbfs >= self._rms_threshold_dbfs, rms_dbfs


@dataclass(frozen=True)
class WakeDetection:
    model_name: str
    score: float
    threshold: float
    detected_at: float
    trigger: str = "normal"
    first_candidate_at: float | None = None
    inference_completed_at: float | None = None
    inference_elapsed_sec: float = 0.0
    lookahead_probe_at: float | None = None
    lookahead_probe_score: float | None = None


@dataclass(frozen=True)
class WakeScoreDecision:
    detected: bool
    trigger: str = ""
    effective_threshold: float = 0.0
    early_count: int = 0


class WakeScorePolicy:
    def __init__(
        self,
        *,
        threshold: float,
        early_threshold: float,
        early_consecutive: int,
    ) -> None:
        if not 0.0 < early_threshold <= threshold <= 1.0:
            raise ValueError(
                "thresholds must satisfy 0 < early_threshold <= threshold <= 1"
            )
        if early_consecutive <= 0:
            raise ValueError("early_consecutive must be greater than zero")
        self._threshold = threshold
        self._early_threshold = early_threshold
        self._early_consecutive = early_consecutive
        self._early_count = 0

    @property
    def early_threshold(self) -> float:
        return self._early_threshold

    def observe(self, score: float) -> WakeScoreDecision:
        if score >= self._threshold:
            self._early_count = 0
            return WakeScoreDecision(
                detected=True,
                trigger="normal",
                effective_threshold=self._threshold,
            )

        if score < self._early_threshold:
            self._early_count = 0
            return WakeScoreDecision(detected=False)

        self._early_count += 1
        if self._early_count >= self._early_consecutive:
            count = self._early_count
            self._early_count = 0
            return WakeScoreDecision(
                detected=True,
                trigger="early",
                effective_threshold=self._early_threshold,
                early_count=count,
            )
        return WakeScoreDecision(
            detected=False,
            early_count=self._early_count,
        )

    def reset_sequence(self) -> None:
        self._early_count = 0


@dataclass(frozen=True)
class InferenceResult:
    generation: int
    captured_at: float
    completed_at: float
    scores: ScoreMap
    lookahead_scores: ScoreMap
    elapsed_sec: float
    lookahead_silence_samples: int = 0
    lookahead_source: str = ""
    error: BaseException | None = None


@dataclass(frozen=True)
class LookaheadProbe:
    captured_at: float
    target_at: float
    model_name: str
    virtual_score: float
    current_score: float
    silence_sec: float
    source: str


class WakeBackend(Protocol):
    requires_off_transcription: bool

    @property
    def inference_count(self) -> int: ...

    @property
    def dropped_count(self) -> int: ...

    def feed_audio(
        self,
        pcm: Int16Array,
        *,
        has_speech: bool,
        now: float,
    ) -> None: ...

    def poll(self, *, now: float) -> WakeDetection | None: ...

    def reset_audio(self) -> None: ...

    def close(self) -> None: ...


class IncrementalWakePredictor:
    """Reuse speech embeddings shared by consecutive 80 ms audio windows."""

    def __init__(self, model: object) -> None:
        self.model = model
        self._previous_audio: Int16Array | None = None
        self._embeddings: NDArray[np.float32] | None = None
        self._cache_hits = 0
        self._cache_misses = 0

    @property
    def cache_hits(self) -> int:
        return self._cache_hits

    @property
    def cache_misses(self) -> int:
        return self._cache_misses

    def __call__(self, audio_chunk: Int16Array) -> ScoreMap:
        from livekit.wakeword.inference.model import (
            EMBEDDING_STRIDE,
            EMBEDDING_WINDOW,
            MIN_EMBEDDINGS,
        )

        classifiers = self.model._classifiers
        if not classifiers:
            return {}

        samples = np.asarray(audio_chunk, dtype=np.int16).reshape(-1)
        float_audio = samples.astype(np.float32) / 32768.0
        all_mel = self.model._mel_frontend(float_audio)
        if all_mel.ndim == 3:
            all_mel = all_mel[0]

        windows = tuple(
            all_mel[start : start + EMBEDDING_WINDOW]
            for start in range(
                0,
                all_mel.shape[0] - EMBEDDING_WINDOW + 1,
                EMBEDDING_STRIDE,
            )
        )
        if len(windows) < MIN_EMBEDDINGS:
            self._replace_cache(samples, None)
            return {name: 0.0 for name in classifiers}

        selected_windows = windows[-MIN_EMBEDDINGS:]
        shift_steps = self._overlap_steps(samples, MIN_EMBEDDINGS)
        if shift_steps is None or self._embeddings is None:
            embeddings = self._embed(selected_windows)
            self._cache_misses += 1
        else:
            retained = self._embeddings[shift_steps:]
            appended = self._embed(selected_windows[-shift_steps:])
            embeddings = np.concatenate((retained, appended), axis=0)
            self._cache_hits += 1

        self._replace_cache(samples, embeddings)
        emb_input = embeddings[np.newaxis, :, :].astype(np.float32)
        predictions: dict[str, float] = {}
        for name, (session, input_name) in classifiers.items():
            outputs = session.run(None, {input_name: emb_input})
            predictions[name] = float(outputs[0][0, 0])
        return predictions

    def predict_silence_lookahead(
        self,
        audio_chunk: Int16Array,
        silence_samples: int,
    ) -> ScoreMap:
        samples = np.asarray(audio_chunk, dtype=np.int16).reshape(-1)
        if not 0 < silence_samples < samples.size:
            raise ValueError("silence_samples must be within the audio window")
        virtual_audio = np.zeros_like(samples)
        virtual_audio[:-silence_samples] = samples[silence_samples:]
        return self.model.predict(virtual_audio)

    def _embed(
        self,
        windows: tuple[NDArray[np.float32], ...],
    ) -> NDArray[np.float32]:
        embeddings = [
            self.model._speech_embedding(window[np.newaxis, :, :])[0]
            for window in windows
        ]
        return np.stack(embeddings, axis=0).astype(np.float32)

    def _overlap_steps(
        self,
        samples: Int16Array,
        max_steps: int,
    ) -> int | None:
        previous = self._previous_audio
        if previous is None or previous.shape != samples.shape:
            return None
        for steps in range(1, max_steps):
            shift = steps * EMBEDDING_STEP_SAMPLES
            if shift >= samples.size:
                break
            if np.array_equal(previous[shift:], samples[:-shift]):
                return steps
        return None

    def _replace_cache(
        self,
        samples: Int16Array,
        embeddings: NDArray[np.float32] | None,
    ) -> None:
        self._previous_audio = samples.copy()
        self._embeddings = None if embeddings is None else embeddings.copy()


def build_cpu_predictor(model_path: Path) -> IncrementalWakePredictor:
    import gc

    import onnxruntime as ort
    from livekit.wakeword import WakeWordModel
    from livekit.wakeword.resources import (
        get_embedding_model_path,
        get_mel_model_path,
    )

    def create_session(path: Path) -> ort.InferenceSession:
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        return ort.InferenceSession(
            str(path),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

    model = WakeWordModel()

    mel_session = create_session(get_mel_model_path())
    model._mel_frontend._onnx_session = mel_session
    model._mel_frontend._input_name = mel_session.get_inputs()[0].name

    embedding_session = create_session(get_embedding_model_path())
    model._speech_embedding._session = embedding_session
    model._speech_embedding._input_name = embedding_session.get_inputs()[0].name

    classifier_session = create_session(model_path)
    model._classifiers = {
        model_path.stem: (
            classifier_session,
            classifier_session.get_inputs()[0].name,
        )
    }
    gc.collect()
    return IncrementalWakePredictor(model)


class AudioWindow:
    def __init__(self, sample_count: int = 32_000) -> None:
        if sample_count <= 0:
            raise ValueError("sample_count must be greater than zero")
        self._capacity = sample_count
        self._chunks: deque[Int16Array] = deque()
        self._stored_sample_count = 0
        self._real_sample_count = 0
        self.reset()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def real_sample_count(self) -> int:
        return self._real_sample_count

    def reset(self) -> None:
        self._chunks.clear()
        self._chunks.append(np.zeros(self._capacity, dtype=np.int16))
        self._stored_sample_count = self._capacity
        self._real_sample_count = 0

    def append(self, pcm: Int16Array) -> None:
        samples = np.asarray(pcm, dtype=np.int16).reshape(-1)
        if samples.size == 0:
            return
        owned = samples[-self._capacity :].copy()
        self._chunks.append(owned)
        self._stored_sample_count += owned.size
        self._real_sample_count = min(
            self._capacity,
            self._real_sample_count + owned.size,
        )
        self._trim_left(self._stored_sample_count - self._capacity)

    def snapshot(self) -> Int16Array:
        if len(self._chunks) == 1:
            return self._chunks[0].copy()
        combined = np.concatenate(tuple(self._chunks))
        if combined.size != self._capacity:
            raise RuntimeError(
                f"audio window invariant failed: {combined.size} != {self._capacity}"
            )
        return combined

    def _trim_left(self, sample_count: int) -> None:
        remaining = sample_count
        while remaining > 0:
            first = self._chunks[0]
            if first.size <= remaining:
                self._chunks.popleft()
                self._stored_sample_count -= first.size
                remaining -= first.size
                continue
            self._chunks[0] = first[remaining:].copy()
            self._stored_sample_count -= remaining
            remaining = 0


class AdaptiveInferenceScheduler:
    def __init__(
        self,
        *,
        active_interval_sec: float,
        idle_interval_sec: float,
        speech_hold_sec: float,
        warmup_samples: int,
    ) -> None:
        self._active_interval_sec = active_interval_sec
        self._idle_interval_sec = idle_interval_sec
        self._speech_hold_sec = speech_hold_sec
        self._warmup_samples = warmup_samples
        self._last_requested_at: float | None = None
        self._last_speech_at: float | None = None
        self._speech_was_active = False

    @property
    def speech_hold_sec(self) -> float:
        return self._speech_hold_sec

    def should_request(
        self,
        *,
        now: float,
        has_speech: bool,
        real_sample_count: int,
    ) -> bool:
        speech_started = has_speech and not self._speech_was_active
        self._speech_was_active = has_speech
        if has_speech:
            self._last_speech_at = now

        if real_sample_count <= 0 or real_sample_count < self._warmup_samples:
            return False

        if speech_started:
            self._last_requested_at = now
            return True

        active = (
            self._last_speech_at is not None
            and now - self._last_speech_at <= self._speech_hold_sec
        )
        interval = (
            self._active_interval_sec if active else self._idle_interval_sec
        )
        if (
            self._last_requested_at is None
            or now - self._last_requested_at >= interval
        ):
            self._last_requested_at = now
            return True
        return False

    def reset(self) -> None:
        self._last_requested_at = None
        self._last_speech_at = None
        self._speech_was_active = False


@dataclass(frozen=True)
class _InferenceRequest:
    generation: int
    captured_at: float
    audio: Int16Array
    lookahead_silence_samples: int = 0
    lookahead_source: str = ""


class LatestWindowWorker:
    def __init__(self, predictor: Predictor) -> None:
        self._predictor = predictor
        self._condition = threading.Condition()
        self._pending: _InferenceRequest | None = None
        self._result: InferenceResult | None = None
        self._closing = False
        self._dropped_count = 0
        self._completed_count = 0
        self._thread = threading.Thread(
            target=self._run,
            name="wakeword-inference",
            daemon=True,
        )
        self._thread.start()

    @property
    def dropped_count(self) -> int:
        with self._condition:
            return self._dropped_count

    @property
    def completed_count(self) -> int:
        with self._condition:
            return self._completed_count

    def submit(
        self,
        audio: Int16Array,
        *,
        generation: int,
        captured_at: float,
        lookahead_silence_samples: int = 0,
        lookahead_source: str = "",
    ) -> None:
        request = _InferenceRequest(
            generation,
            captured_at,
            audio.copy(),
            lookahead_silence_samples,
            lookahead_source,
        )
        with self._condition:
            if self._closing:
                return
            if self._pending is not None:
                self._dropped_count += 1
                if not self._can_replace(self._pending, request):
                    return
            self._pending = request
            self._condition.notify()

    def poll(self) -> InferenceResult | None:
        with self._condition:
            result = self._result
            self._result = None
            return result

    def close(self) -> None:
        with self._condition:
            self._closing = True
            self._pending = None
            self._condition.notify()
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            logging.warning("wake word worker did not stop within timeout")

    def _run(self) -> None:
        while True:
            with self._condition:
                while self._pending is None and not self._closing:
                    self._condition.wait()
                if self._closing:
                    return
                request = self._pending
                self._pending = None
            assert request is not None

            started_at = time.monotonic()
            error: BaseException | None = None
            scores: ScoreMap = {}
            lookahead_scores: ScoreMap = {}
            try:
                scores = dict(self._predictor(request.audio))
            except BaseException as exc:  # worker境界で主loopへ通知する
                error = exc

            lookahead_method = getattr(
                self._predictor,
                "predict_silence_lookahead",
                None,
            )
            if (
                error is None
                and request.lookahead_silence_samples > 0
                and callable(lookahead_method)
            ):
                try:
                    lookahead_scores = dict(
                        lookahead_method(
                            request.audio,
                            request.lookahead_silence_samples,
                        )
                    )
                except Exception:
                    logging.exception("wake lookahead inference failed")
            completed_at = time.monotonic()
            result = InferenceResult(
                generation=request.generation,
                captured_at=request.captured_at,
                completed_at=completed_at,
                scores=scores,
                lookahead_scores=lookahead_scores,
                elapsed_sec=completed_at - started_at,
                lookahead_silence_samples=request.lookahead_silence_samples,
                lookahead_source=request.lookahead_source,
                error=error,
            )
            with self._condition:
                if self._result is None or self._can_replace(
                    self._result,
                    result,
                ):
                    self._result = result
                else:
                    self._dropped_count += 1
                self._completed_count += 1

    @staticmethod
    def _can_replace(
        existing: _InferenceRequest | InferenceResult,
        incoming: _InferenceRequest | InferenceResult,
    ) -> bool:
        if existing.generation != incoming.generation:
            return True
        existing_is_lookahead = existing.lookahead_silence_samples > 0
        incoming_is_lookahead = incoming.lookahead_silence_samples > 0
        return not existing_is_lookahead or incoming_is_lookahead


class LiveKitWakeBackend:
    requires_off_transcription = False

    def __init__(
        self,
        *,
        model_path: Path,
        threshold: float,
        debounce_sec: float,
        active_interval_sec: float,
        idle_interval_sec: float,
        speech_hold_sec: float,
        warmup_sec: float,
        lookahead_mode: str = "off",
        lookahead_target_sec: float = 2.0,
        lookahead_max_silence_sec: float = 1.5,
        lookahead_silence_chunks: int = 2,
        lookahead_trigger_score: float = 0.10,
        lookahead_threshold: float = 0.55,
        early_threshold: float = 0.15,
        early_consecutive: int = 3,
        predictor: Predictor | None = None,
    ) -> None:
        if predictor is None:
            predictor = build_cpu_predictor(model_path)
        self._window = AudioWindow()
        self._scheduler = AdaptiveInferenceScheduler(
            active_interval_sec=active_interval_sec,
            idle_interval_sec=idle_interval_sec,
            speech_hold_sec=speech_hold_sec,
            warmup_samples=round(warmup_sec * 16_000),
        )
        self._worker = LatestWindowWorker(predictor)
        self._threshold = threshold
        self._score_policy = WakeScorePolicy(
            threshold=threshold,
            early_threshold=early_threshold,
            early_consecutive=early_consecutive,
        )
        self._debounce_sec = debounce_sec
        self._lookahead_mode = lookahead_mode
        self._lookahead_target_sec = lookahead_target_sec
        self._lookahead_target_samples = round(
            lookahead_target_sec * 16_000
        )
        self._lookahead_max_silence_samples = round(
            lookahead_max_silence_sec * 16_000
        )
        self._lookahead_silence_chunks = lookahead_silence_chunks
        self._lookahead_trigger_score = lookahead_trigger_score
        self._lookahead_threshold = lookahead_threshold
        self._lookahead_armed = False
        self._lookahead_inactive_chunks = 0
        self._lookahead_activity_started_at: float | None = None
        self._lookahead_activity_started_sample: int | None = None
        self._lookahead_last_activity_at: float | None = None
        self._lookahead_sample_cursor = 0
        self._lookahead_probe: LookaheadProbe | None = None
        self._last_score_lookahead_at: float | None = None
        self._generation = 0
        self._last_detection_at: float | None = None
        self._first_candidate_at: float | None = None
        self._fatal_error: BaseException | None = None

    @property
    def dropped_count(self) -> int:
        return self._worker.dropped_count

    @property
    def inference_count(self) -> int:
        return self._worker.completed_count

    def feed_audio(
        self,
        pcm: Int16Array,
        *,
        has_speech: bool,
        now: float,
    ) -> None:
        self._raise_if_unhealthy()
        self._window.append(pcm)
        lookahead_silence_samples = self._observe_lookahead_activity(
            has_speech,
            now,
            sample_count=np.asarray(pcm).size,
        )
        request_inference = self._scheduler.should_request(
            now=now,
            has_speech=has_speech,
            real_sample_count=self._window.real_sample_count,
        )
        if request_inference or lookahead_silence_samples > 0:
            self._worker.submit(
                self._window.snapshot(),
                generation=self._generation,
                captured_at=now,
                lookahead_silence_samples=lookahead_silence_samples,
                lookahead_source=(
                    "vad" if lookahead_silence_samples > 0 else ""
                ),
            )

    def poll(self, *, now: float) -> WakeDetection | None:
        self._raise_if_unhealthy()
        result = self._worker.poll()
        if result is None or result.generation != self._generation:
            return None
        if result.error is not None:
            self._fatal_error = result.error
            self._raise_if_unhealthy()
        if not result.scores:
            return None

        model_name, score = max(result.scores.items(), key=lambda item: item[1])
        self._observe_lookahead_result(result, model_name, score)
        lookahead_detection = self._detect_from_lookahead(result)
        if lookahead_detection is not None:
            return lookahead_detection
        self._request_score_lookahead(result, score, now)
        logging.debug(
            "wake inference model=%s score=%.4f elapsed_ms=%.1f dropped=%d",
            model_name,
            score,
            result.elapsed_sec * 1000,
            self.dropped_count,
        )
        if score >= self._score_policy.early_threshold:
            if self._first_candidate_at is None:
                self._first_candidate_at = result.captured_at
        else:
            self._first_candidate_at = None

        decision = self._score_policy.observe(score)
        if self._score_policy.early_threshold <= score < self._threshold:
            logging.info(
                (
                    "wake candidate model=%s score=%.4f threshold=%.4f "
                    "early_count=%d elapsed_ms=%.1f"
                ),
                model_name,
                score,
                self._threshold,
                decision.early_count,
                result.elapsed_sec * 1000,
            )
        if not decision.detected:
            return None
        if (
            self._last_detection_at is not None
            and result.captured_at - self._last_detection_at < self._debounce_sec
        ):
            logging.debug(
                "wake detection ignored by debounce score=%.4f",
                score,
            )
            return None
        self._last_detection_at = result.captured_at
        first_candidate_at = self._first_candidate_at
        self._first_candidate_at = None
        lookahead_probe = self._lookahead_probe
        if (
            lookahead_probe is not None
            and result.captured_at < lookahead_probe.target_at
        ):
            logging.info(
                (
                    "wake lookahead validation outcome=detection_before_target "
                    "virtual_score=%.4f current_score=%.4f "
                    "probe_to_detection_ms=%.1f target_remaining_ms=%.1f"
                ),
                lookahead_probe.virtual_score,
                lookahead_probe.current_score,
                (result.captured_at - lookahead_probe.captured_at) * 1000.0,
                (lookahead_probe.target_at - result.captured_at) * 1000.0,
            )
        self._lookahead_probe = None
        return WakeDetection(
            model_name=model_name,
            score=score,
            threshold=decision.effective_threshold,
            detected_at=result.captured_at,
            trigger=decision.trigger,
            first_candidate_at=first_candidate_at,
            inference_completed_at=result.completed_at,
            inference_elapsed_sec=result.elapsed_sec,
            lookahead_probe_at=(
                None if lookahead_probe is None else lookahead_probe.captured_at
            ),
            lookahead_probe_score=(
                None if lookahead_probe is None else lookahead_probe.virtual_score
            ),
        )

    def reset_audio(self) -> None:
        self._generation += 1
        self._window.reset()
        self._scheduler.reset()
        self._score_policy.reset_sequence()
        self._first_candidate_at = None
        self._lookahead_armed = False
        self._lookahead_inactive_chunks = 0
        self._lookahead_activity_started_at = None
        self._lookahead_activity_started_sample = None
        self._lookahead_last_activity_at = None
        self._lookahead_sample_cursor = 0
        self._lookahead_probe = None
        self._last_score_lookahead_at = None

    def close(self) -> None:
        self._worker.close()

    def _raise_if_unhealthy(self) -> None:
        if self._fatal_error is not None:
            raise RuntimeError("wake word inference worker failed") from self._fatal_error

    def _observe_lookahead_activity(
        self,
        has_speech: bool,
        now: float,
        *,
        sample_count: int = 0,
    ) -> int:
        chunk_started_sample = self._lookahead_sample_cursor
        self._lookahead_sample_cursor += sample_count
        if self._lookahead_mode not in {"shadow", "active"}:
            return 0
        if has_speech:
            if (
                self._lookahead_last_activity_at is None
                or now - self._lookahead_last_activity_at
                > self._scheduler.speech_hold_sec
            ):
                self._lookahead_activity_started_at = now
                self._lookahead_activity_started_sample = (
                    chunk_started_sample if sample_count > 0 else None
                )
            self._lookahead_last_activity_at = now
            self._lookahead_armed = True
            self._lookahead_inactive_chunks = 0
            return 0
        if not self._lookahead_armed:
            return 0
        self._lookahead_inactive_chunks += 1
        if self._lookahead_inactive_chunks < self._lookahead_silence_chunks:
            return 0
        self._lookahead_armed = False
        self._lookahead_inactive_chunks = 0
        silence_samples = self._lookahead_samples_at(now)
        started_sample = self._lookahead_activity_started_sample
        observed_samples = (
            None
            if started_sample is None
            else self._lookahead_sample_cursor - started_sample
        )
        logging.info(
            (
                "wake lookahead window source=vad observed_samples=%s "
                "observed_ms=%s wall_ms=%s silence_samples=%d silence_ms=%.1f"
            ),
            "n/a" if observed_samples is None else observed_samples,
            (
                "n/a"
                if observed_samples is None
                else f"{observed_samples / 16.0:.1f}"
            ),
            (
                "n/a"
                if self._lookahead_activity_started_at is None
                else f"{(now - self._lookahead_activity_started_at) * 1000.0:.1f}"
            ),
            silence_samples,
            silence_samples / 16.0,
        )
        return silence_samples

    def _observe_lookahead_result(
        self,
        result: InferenceResult,
        model_name: str,
        actual_score: float,
    ) -> None:
        self._validate_lookahead_probe(result, model_name, actual_score)
        if not result.lookahead_scores:
            return
        shadow_model, shadow_score = max(
            result.lookahead_scores.items(),
            key=lambda item: item[1],
        )
        silence_sec = result.lookahead_silence_samples / 16_000.0
        self._lookahead_probe = LookaheadProbe(
            captured_at=result.captured_at,
            target_at=result.captured_at + silence_sec,
            model_name=shadow_model,
            virtual_score=shadow_score,
            current_score=actual_score,
            silence_sec=silence_sec,
            source=result.lookahead_source,
        )
        logging.info(
            (
                "wake lookahead probe source=%s model=%s virtual_score=%.4f "
                "actual_model=%s actual_score=%.4f silence_sec=%.2f "
                "target_in_ms=%.1f"
            ),
            result.lookahead_source or "unknown",
            shadow_model,
            shadow_score,
            model_name,
            actual_score,
            silence_sec,
            silence_sec * 1000.0,
        )

    def _validate_lookahead_probe(
        self,
        result: InferenceResult,
        model_name: str,
        actual_score: float,
    ) -> None:
        probe = self._lookahead_probe
        if probe is None or result.captured_at < probe.target_at:
            return
        score_delta = actual_score - probe.virtual_score
        logging.info(
            (
                "wake lookahead validation outcome=target_reached "
                "model=%s actual_model=%s virtual_score=%.4f "
                "future_score=%.4f score_delta=%+.4f abs_delta=%.4f "
                "target_lag_ms=%.1f normal_match=%s early_match=%s"
            ),
            probe.model_name,
            model_name,
            probe.virtual_score,
            actual_score,
            score_delta,
            abs(score_delta),
            (result.captured_at - probe.target_at) * 1000.0,
            (probe.virtual_score >= self._threshold)
            == (actual_score >= self._threshold),
            (probe.virtual_score >= self._score_policy.early_threshold)
            == (actual_score >= self._score_policy.early_threshold),
        )
        self._lookahead_probe = None

    def _detect_from_lookahead(
        self,
        result: InferenceResult,
    ) -> WakeDetection | None:
        if self._lookahead_mode != "active" or not result.lookahead_scores:
            return None
        model_name, score = max(
            result.lookahead_scores.items(),
            key=lambda item: item[1],
        )
        probe = self._lookahead_probe
        current_score = (
            probe.current_score
            if probe is not None
            else max(result.scores.values(), default=0.0)
        )
        if score < self._lookahead_threshold:
            return None
        if (
            (probe is None or probe.source != "vad")
            and current_score < self._lookahead_trigger_score
        ):
            return None
        if (
            self._last_detection_at is not None
            and result.captured_at - self._last_detection_at < self._debounce_sec
        ):
            logging.debug(
                "wake lookahead detection ignored by debounce score=%.4f",
                score,
            )
            self._lookahead_probe = None
            return None

        self._last_detection_at = result.captured_at
        first_candidate_at = self._first_candidate_at or result.captured_at
        self._first_candidate_at = None
        self._score_policy.reset_sequence()
        self._lookahead_probe = None
        logging.info(
            (
                "wake lookahead activated model=%s current_score=%.4f "
                "virtual_score=%.4f trigger_score=%.4f threshold=%.4f "
                "source=%s silence_sec=%.2f elapsed_ms=%.1f"
            ),
            model_name,
            current_score,
            score,
            self._lookahead_trigger_score,
            self._lookahead_threshold,
            "unknown" if probe is None else probe.source,
            0.0 if probe is None else probe.silence_sec,
            result.elapsed_sec * 1000.0,
        )
        return WakeDetection(
            model_name=model_name,
            score=score,
            threshold=self._lookahead_threshold,
            detected_at=result.captured_at,
            trigger="lookahead",
            first_candidate_at=first_candidate_at,
            inference_completed_at=result.completed_at,
            inference_elapsed_sec=result.elapsed_sec,
            lookahead_probe_at=(
                None if probe is None else probe.captured_at
            ),
            lookahead_probe_score=(
                None if probe is None else probe.virtual_score
            ),
        )

    def _request_score_lookahead(
        self,
        result: InferenceResult,
        score: float,
        now: float,
    ) -> None:
        if (
            self._lookahead_mode != "active"
            or result.lookahead_scores
            or not self._lookahead_trigger_score <= score < self._threshold
        ):
            return
        if (
            self._last_score_lookahead_at is not None
            and now - self._last_score_lookahead_at < 0.25
        ):
            return
        self._last_score_lookahead_at = now
        silence_samples = self._lookahead_samples_at(now)
        if silence_samples <= 0:
            return
        self._worker.submit(
            self._window.snapshot(),
            generation=self._generation,
            captured_at=now,
            lookahead_silence_samples=silence_samples,
            lookahead_source="score",
        )
        logging.info(
            (
                "wake lookahead requested by score score=%.4f "
                "trigger_score=%.4f silence_ms=%.1f"
            ),
            score,
            self._lookahead_trigger_score,
            silence_samples / 16.0,
        )

    def _lookahead_samples_at(self, now: float) -> int:
        started_sample = self._lookahead_activity_started_sample
        if started_sample is not None:
            observed_samples = self._lookahead_sample_cursor - started_sample
            remaining_samples = self._lookahead_target_samples - observed_samples
        else:
            started_at = self._lookahead_activity_started_at
            if started_at is None:
                return 0
            remaining_samples = round(
                (self._lookahead_target_sec - (now - started_at)) * 16_000
            )
        if remaining_samples < EMBEDDING_STEP_SAMPLES:
            return 0
        return min(
            remaining_samples,
            self._lookahead_max_silence_samples,
        )


class SttWakeBackend:
    requires_off_transcription = True

    @property
    def inference_count(self) -> int:
        return 0

    @property
    def dropped_count(self) -> int:
        return 0

    def feed_audio(
        self,
        pcm: Int16Array,
        *,
        has_speech: bool,
        now: float,
    ) -> None:
        del pcm, has_speech, now

    def poll(self, *, now: float) -> WakeDetection | None:
        del now
        return None

    def reset_audio(self) -> None:
        return

    def close(self) -> None:
        return
