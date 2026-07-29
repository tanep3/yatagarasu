from __future__ import annotations

from dataclasses import dataclass

from wakeword import WakeDetection


def elapsed_ms(start: float | None, end: float | None) -> float | None:
    if start is None or end is None:
        return None
    return max(0.0, end - start) * 1000.0


def format_ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}"


@dataclass
class WakeLatencyTrace:
    trace_id: str
    activity_source: str
    activity_started_at: float | None
    first_candidate_at: float | None
    inference_captured_at: float
    inference_completed_at: float | None
    detection_observed_at: float
    inference_elapsed_sec: float
    prompt_start_requested_at: float | None = None
    prompt_process_started_at: float | None = None
    prompt_terminal_at: float | None = None
    prompt_status: str = ""


class WakeLatencyTracker:
    """Collect timestamps for one wake-to-prompt transaction."""

    def __init__(self, *, activity_hold_sec: float) -> None:
        if activity_hold_sec < 0:
            raise ValueError("activity_hold_sec must not be negative")
        self._activity_hold_sec = activity_hold_sec
        self._sequence = 0
        self._activity_started_at: float | None = None
        self._activity_last_at: float | None = None
        self._activity_source = "unknown"
        self._current: WakeLatencyTrace | None = None

    @property
    def current(self) -> WakeLatencyTrace | None:
        return self._current

    def observe_activity(self, *, now: float, active: bool, source: str) -> bool:
        if not active:
            return False
        starts_new_episode = (
            self._activity_last_at is None
            or now - self._activity_last_at > self._activity_hold_sec
        )
        if starts_new_episode:
            self._activity_started_at = now
            self._activity_source = source
        self._activity_last_at = now
        return starts_new_episode

    def on_detection(
        self,
        detection: WakeDetection,
        *,
        observed_at: float,
    ) -> WakeLatencyTrace:
        self._sequence += 1
        activity_is_recent = (
            self._activity_last_at is not None
            and detection.detected_at - self._activity_last_at
            <= self._activity_hold_sec
        )
        trace = WakeLatencyTrace(
            trace_id=f"wake-{self._sequence:06d}",
            activity_source=(
                self._activity_source if activity_is_recent else "unknown"
            ),
            activity_started_at=(
                self._activity_started_at if activity_is_recent else None
            ),
            first_candidate_at=detection.first_candidate_at,
            inference_captured_at=detection.detected_at,
            inference_completed_at=detection.inference_completed_at,
            detection_observed_at=observed_at,
            inference_elapsed_sec=detection.inference_elapsed_sec,
        )
        self._current = trace
        self._activity_started_at = None
        self._activity_last_at = None
        self._activity_source = "unknown"
        return trace

    def on_prompt_start_requested(self, *, now: float) -> None:
        if self._current is not None:
            self._current.prompt_start_requested_at = now

    def on_prompt_process_started(self, *, now: float) -> None:
        if self._current is not None:
            self._current.prompt_process_started_at = now

    def on_prompt_terminal(self, *, now: float, status: str) -> None:
        if self._current is not None:
            self._current.prompt_terminal_at = now
            self._current.prompt_status = status

    def reset(self) -> None:
        self._activity_started_at = None
        self._activity_last_at = None
        self._activity_source = "unknown"
        self._current = None
