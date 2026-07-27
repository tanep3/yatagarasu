from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ListenState(str, Enum):
    OFF = "OFF"
    WAKING = "WAKING"
    ON = "ON"


class SessionAction(str, Enum):
    NONE = "NONE"
    START_PROMPT = "START_PROMPT"
    ENTER_ON = "ENTER_ON"
    ENTER_OFF = "ENTER_OFF"
    DISPATCH = "DISPATCH"


@dataclass(frozen=True)
class SessionDecision:
    action: SessionAction
    reason: str = ""


class ListenSession:
    def __init__(
        self,
        *,
        prompt_guard_sec: float,
        session_end_silence_sec: float,
        silence_timeout_sec: float,
    ) -> None:
        self._prompt_guard_sec = prompt_guard_sec
        self._session_end_silence_sec = session_end_silence_sec
        self._silence_timeout_sec = silence_timeout_sec
        self.state = ListenState.OFF
        self._last_activity_at = 0.0
        self._prompt_guard_deadline: float | None = None

    def on_livekit_wake(self, now: float) -> SessionDecision:
        if self.state is not ListenState.OFF:
            return SessionDecision(SessionAction.NONE)
        self.state = ListenState.WAKING
        self._prompt_guard_deadline = None
        return SessionDecision(
            SessionAction.START_PROMPT,
            "ONNX wake word detected",
        )

    def on_stt_wake(self, now: float) -> SessionDecision:
        if self.state is not ListenState.OFF:
            return SessionDecision(SessionAction.NONE)
        self.state = ListenState.ON
        self._last_activity_at = now
        return SessionDecision(
            SessionAction.ENTER_ON,
            "STT wake word detected",
        )

    def on_prompt_succeeded(self, now: float) -> SessionDecision:
        if self.state is not ListenState.WAKING:
            return SessionDecision(SessionAction.NONE)
        if self._prompt_guard_sec <= 0:
            return self._enter_on(now, "wake prompt completed")
        self._prompt_guard_deadline = now + self._prompt_guard_sec
        return SessionDecision(SessionAction.NONE, "wake prompt guard started")

    def on_prompt_failed(self, now: float, reason: str) -> SessionDecision:
        if self.state is not ListenState.WAKING:
            return SessionDecision(SessionAction.NONE)
        return self._enter_on(now, reason)

    def on_voice_detected(self, now: float) -> None:
        if self.state is ListenState.ON:
            self._last_activity_at = now

    def on_dispatch_completed(self, now: float) -> None:
        if self.state is ListenState.ON:
            self._last_activity_at = now

    def on_stop(self, now: float, reason: str) -> SessionDecision:
        del now
        if self.state is ListenState.OFF:
            return SessionDecision(SessionAction.NONE)
        self.state = ListenState.OFF
        self._prompt_guard_deadline = None
        return SessionDecision(SessionAction.ENTER_OFF, reason)

    def on_reconnect(self, now: float) -> SessionDecision:
        del now
        changed = self.state is not ListenState.OFF
        self.state = ListenState.OFF
        self._prompt_guard_deadline = None
        return SessionDecision(
            SessionAction.ENTER_OFF if changed else SessionAction.NONE,
            "RTSP reconnect",
        )

    def tick(self, now: float, *, has_pending_text: bool) -> SessionDecision:
        if self.state is ListenState.WAKING:
            if (
                self._prompt_guard_deadline is not None
                and now >= self._prompt_guard_deadline
            ):
                return self._enter_on(now, "wake prompt guard elapsed")
            return SessionDecision(SessionAction.NONE)

        if self.state is not ListenState.ON:
            return SessionDecision(SessionAction.NONE)

        idle_sec = max(0.0, now - self._last_activity_at)
        if has_pending_text and idle_sec >= self._session_end_silence_sec:
            return SessionDecision(
                SessionAction.DISPATCH,
                (
                    f"session end silence ({idle_sec:.1f}s >= "
                    f"{self._session_end_silence_sec:.1f}s)"
                ),
            )
        if not has_pending_text and idle_sec >= self._silence_timeout_sec:
            self.state = ListenState.OFF
            return SessionDecision(
                SessionAction.ENTER_OFF,
                (
                    f"cancel empty session ({idle_sec:.1f}s >= "
                    f"{self._silence_timeout_sec:.1f}s)"
                ),
            )
        return SessionDecision(SessionAction.NONE)

    def _enter_on(self, now: float, reason: str) -> SessionDecision:
        self.state = ListenState.ON
        self._last_activity_at = now
        self._prompt_guard_deadline = None
        return SessionDecision(SessionAction.ENTER_ON, reason)
