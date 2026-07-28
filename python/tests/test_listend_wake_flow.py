from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from audio_prompt import PromptStatus
from listen_state import ListenSession, ListenState, SessionAction, SessionDecision
from listend import ListendService
from wakeword import WakeActivityGate, WakeDetection


class FakeWakeBackend:
    requires_off_transcription = False

    def __init__(self) -> None:
        self.feed_count = 0
        self.reset_count = 0
        self.detection: WakeDetection | None = None

    def feed_audio(self, pcm, *, has_speech: bool, now: float) -> None:
        del pcm, has_speech, now
        self.feed_count += 1

    def poll(self, *, now: float) -> WakeDetection | None:
        del now
        detection = self.detection
        self.detection = None
        return detection

    def reset_audio(self) -> None:
        self.reset_count += 1

    def close(self) -> None:
        return


class FakePromptPlayer:
    def __init__(self) -> None:
        self.status = PromptStatus.IDLE
        self.started = 0

    def start(self, audio_path, *, now: float) -> None:
        del audio_path, now
        self.started += 1
        self.status = PromptStatus.RUNNING

    def poll(self, *, now: float) -> PromptStatus:
        del now
        return self.status

    def close(self) -> None:
        self.status = PromptStatus.IDLE


def new_service() -> tuple[ListendService, FakeWakeBackend, FakePromptPlayer]:
    service = object.__new__(ListendService)
    service.settings = SimpleNamespace(
        wake=SimpleNamespace(
            prompt_audio_path=SimpleNamespace(),
        ),
        wake_suppression_sec=0.0,
    )
    service.session = ListenSession(
        prompt_guard_sec=0.8,
        session_end_silence_sec=3.0,
        silence_timeout_sec=3.0,
    )
    service.in_segment = False
    service.trailing_silence_chunks = 0
    service.segment_buffer = bytearray()
    service.vad_hangover_remaining = 0
    service.session_text_chunks = []
    service.wake_ack_pending = False
    service.last_system_audio_at = 0.0
    service._handled_prompt_status = PromptStatus.IDLE
    service._wake_suppressed = False
    service._wake_rms_active = False
    service._reset_audio_input_after_dispatch = False
    service._has_speech = lambda pcm: True
    service._feed_segment = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("STT segment path must not run while OFF/livekit")
    )
    backend = FakeWakeBackend()
    prompt = FakePromptPlayer()
    service.wake_backend = backend
    service.wake_activity_gate = WakeActivityGate(-50.0)
    service.prompt_player = prompt
    return service, backend, prompt


def test_livekit_off_does_not_build_stt_segment(monkeypatch) -> None:
    service, backend, _ = new_service()
    monkeypatch.setattr("listend.time.monotonic", lambda: 1.0)

    service._process_chunk(np.ones(1_280, dtype=np.int16).tobytes())

    assert backend.feed_count == 1
    assert service.state is ListenState.OFF


def test_livekit_detection_starts_prompt_then_enters_on(monkeypatch) -> None:
    service, backend, prompt = new_service()
    backend.detection = WakeDetection(
        model_name="nee_yatagarasu",
        score=0.8,
        threshold=0.6,
        detected_at=1.0,
    )
    monkeypatch.setattr("listend.time.monotonic", lambda: 1.0)

    service._process_chunk(np.ones(1_280, dtype=np.int16).tobytes())

    assert service.state is ListenState.WAKING
    assert prompt.started == 1

    prompt.status = PromptStatus.SUCCEEDED
    service._poll_waking(1.1)
    assert service.state is ListenState.WAKING
    service._poll_waking(1.91)
    assert service.state is ListenState.ON


def test_prompt_timeout_enters_on_without_guard() -> None:
    service, _, prompt = new_service()
    service.session.on_livekit_wake(1.0)
    service._handled_prompt_status = PromptStatus.RUNNING
    prompt.status = PromptStatus.TIMED_OUT

    service._poll_waking(1.1)

    assert service.state is ListenState.ON


def test_llm_dispatch_enters_off_and_requests_audio_reset() -> None:
    service, _, _ = new_service()
    service.session.on_stt_wake(1.0)
    service._dispatch_session = lambda reason: True

    service._apply_session_decision(
        SessionDecision(SessionAction.DISPATCH, "test"),
        4.0,
    )

    assert service.state is ListenState.OFF
    assert service._reset_audio_input_after_dispatch is True


def test_router_only_dispatch_enters_off_without_audio_reset() -> None:
    service, _, _ = new_service()
    service.session.on_stt_wake(1.0)
    service._dispatch_session = lambda reason: False

    service._apply_session_decision(
        SessionDecision(SessionAction.DISPATCH, "test"),
        4.0,
    )

    assert service.state is ListenState.OFF
    assert service._reset_audio_input_after_dispatch is False
