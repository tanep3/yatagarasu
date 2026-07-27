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


@dataclass(frozen=True)
class WakeDetection:
    model_name: str
    score: float
    threshold: float
    detected_at: float


@dataclass(frozen=True)
class InferenceResult:
    generation: int
    captured_at: float
    scores: ScoreMap
    elapsed_sec: float
    error: BaseException | None = None


class WakeBackend(Protocol):
    requires_off_transcription: bool

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


def build_cpu_predictor(model_path: Path) -> Predictor:
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
    return model.predict


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


class LatestWindowWorker:
    def __init__(self, predictor: Predictor) -> None:
        self._predictor = predictor
        self._condition = threading.Condition()
        self._pending: _InferenceRequest | None = None
        self._result: InferenceResult | None = None
        self._closing = False
        self._dropped_count = 0
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

    def submit(
        self,
        audio: Int16Array,
        *,
        generation: int,
        captured_at: float,
    ) -> None:
        request = _InferenceRequest(generation, captured_at, audio.copy())
        with self._condition:
            if self._closing:
                return
            if self._pending is not None:
                self._dropped_count += 1
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

            started_at = time.perf_counter()
            error: BaseException | None = None
            scores: ScoreMap = {}
            try:
                scores = dict(self._predictor(request.audio))
            except BaseException as exc:  # worker境界で主loopへ通知する
                error = exc
            result = InferenceResult(
                generation=request.generation,
                captured_at=request.captured_at,
                scores=scores,
                elapsed_sec=time.perf_counter() - started_at,
                error=error,
            )
            with self._condition:
                self._result = result


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
        self._debounce_sec = debounce_sec
        self._generation = 0
        self._last_detection_at: float | None = None
        self._fatal_error: BaseException | None = None

    @property
    def dropped_count(self) -> int:
        return self._worker.dropped_count

    def feed_audio(
        self,
        pcm: Int16Array,
        *,
        has_speech: bool,
        now: float,
    ) -> None:
        self._raise_if_unhealthy()
        self._window.append(pcm)
        if self._scheduler.should_request(
            now=now,
            has_speech=has_speech,
            real_sample_count=self._window.real_sample_count,
        ):
            self._worker.submit(
                self._window.snapshot(),
                generation=self._generation,
                captured_at=now,
            )

    def poll(self, *, now: float) -> WakeDetection | None:
        del now
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
        logging.debug(
            "wake inference model=%s score=%.4f elapsed_ms=%.1f dropped=%d",
            model_name,
            score,
            result.elapsed_sec * 1000,
            self.dropped_count,
        )
        if score < self._threshold:
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
        return WakeDetection(
            model_name=model_name,
            score=score,
            threshold=self._threshold,
            detected_at=result.captured_at,
        )

    def reset_audio(self) -> None:
        self._generation += 1
        self._window.reset()
        self._scheduler.reset()

    def close(self) -> None:
        self._worker.close()

    def _raise_if_unhealthy(self) -> None:
        if self._fatal_error is not None:
            raise RuntimeError("wake word inference worker failed") from self._fatal_error


class SttWakeBackend:
    requires_off_transcription = True

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
