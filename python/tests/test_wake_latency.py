from __future__ import annotations

from wake_latency import WakeLatencyTracker, elapsed_ms, format_ms
from wakeword import WakeDetection


def test_tracker_keeps_activity_start_across_short_silence() -> None:
    tracker = WakeLatencyTracker(activity_hold_sec=2.0)

    assert tracker.observe_activity(now=1.0, active=True, source="vad")
    assert not tracker.observe_activity(now=1.1, active=True, source="rms")
    assert not tracker.observe_activity(now=1.2, active=False, source="rms")
    assert not tracker.observe_activity(now=2.9, active=True, source="vad")

    trace = tracker.on_detection(
        WakeDetection(
            model_name="wake",
            score=0.8,
            threshold=0.65,
            detected_at=3.0,
            first_candidate_at=2.84,
            inference_completed_at=3.01,
            inference_elapsed_sec=0.01,
        ),
        observed_at=3.02,
    )

    assert trace.trace_id == "wake-000001"
    assert trace.activity_started_at == 1.0
    assert trace.activity_source == "vad"
    assert elapsed_ms(trace.activity_started_at, trace.inference_captured_at) == 2000.0


def test_tracker_starts_new_activity_after_hold_expires() -> None:
    tracker = WakeLatencyTracker(activity_hold_sec=2.0)

    tracker.observe_activity(now=1.0, active=True, source="rms")
    assert tracker.observe_activity(now=3.1, active=True, source="vad")
    trace = tracker.on_detection(
        WakeDetection(
            model_name="wake",
            score=0.8,
            threshold=0.65,
            detected_at=3.2,
        ),
        observed_at=3.3,
    )

    assert trace.activity_started_at == 3.1
    assert trace.activity_source == "vad"


def test_tracker_records_prompt_timestamps() -> None:
    tracker = WakeLatencyTracker(activity_hold_sec=2.0)
    tracker.on_detection(
        WakeDetection(
            model_name="wake",
            score=0.8,
            threshold=0.65,
            detected_at=1.0,
        ),
        observed_at=1.1,
    )

    tracker.on_prompt_start_requested(now=1.1)
    tracker.on_prompt_process_started(now=1.12)
    tracker.on_prompt_terminal(now=1.4, status="SUCCEEDED")

    trace = tracker.current
    assert trace is not None
    assert trace.prompt_start_requested_at == 1.1
    assert trace.prompt_process_started_at == 1.12
    assert trace.prompt_terminal_at == 1.4
    assert trace.prompt_status == "SUCCEEDED"
    assert format_ms(elapsed_ms(1.12, 1.4)) == "280.0"
    assert format_ms(None) == "n/a"
