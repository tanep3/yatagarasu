from listen_state import ListenSession, ListenState, SessionAction


def new_session(
    *,
    prompt_guard_sec: float = 0.8,
    session_end_silence_sec: float = 3.0,
    silence_timeout_sec: float = 3.0,
) -> ListenSession:
    return ListenSession(
        prompt_guard_sec=prompt_guard_sec,
        session_end_silence_sec=session_end_silence_sec,
        silence_timeout_sec=silence_timeout_sec,
    )


def test_livekit_wake_waits_for_prompt_and_guard() -> None:
    session = new_session()

    decision = session.on_livekit_wake(10.0)
    assert decision.action is SessionAction.START_PROMPT
    assert session.state is ListenState.WAKING

    decision = session.on_prompt_succeeded(10.2)
    assert decision.action is SessionAction.NONE
    assert session.tick(10.99, has_pending_text=False).action is SessionAction.NONE

    decision = session.tick(11.0, has_pending_text=False)
    assert decision.action is SessionAction.ENTER_ON
    assert session.state is ListenState.ON


def test_prompt_failure_enters_on_without_guard() -> None:
    session = new_session()
    session.on_livekit_wake(1.0)

    decision = session.on_prompt_failed(1.1, "prompt failed")

    assert decision.action is SessionAction.ENTER_ON
    assert session.state is ListenState.ON


def test_empty_session_waits_for_timeout() -> None:
    session = new_session(silence_timeout_sec=3.0)
    session.on_stt_wake(5.0)

    assert session.tick(7.99, has_pending_text=False).action is SessionAction.NONE
    decision = session.tick(8.0, has_pending_text=False)

    assert decision.action is SessionAction.ENTER_OFF
    assert session.state is ListenState.OFF


def test_dispatch_has_priority_over_off() -> None:
    session = new_session(
        session_end_silence_sec=3.0,
        silence_timeout_sec=3.0,
    )
    session.on_stt_wake(5.0)

    decision = session.tick(8.0, has_pending_text=True)

    assert decision.action is SessionAction.DISPATCH
    assert session.state is ListenState.ON


def test_dispatch_completion_enters_off() -> None:
    session = new_session(silence_timeout_sec=3.0)
    session.on_stt_wake(5.0)

    decision = session.on_dispatch_completed(8.0)

    assert decision.action is SessionAction.ENTER_OFF
    assert session.state is ListenState.OFF


def test_dispatch_completion_is_ignored_while_off() -> None:
    session = new_session()

    decision = session.on_dispatch_completed(8.0)

    assert decision.action is SessionAction.NONE
    assert session.state is ListenState.OFF


def test_voice_detection_extends_session() -> None:
    session = new_session(silence_timeout_sec=3.0)
    session.on_stt_wake(5.0)
    session.on_voice_detected(7.0)

    assert session.tick(9.99, has_pending_text=False).action is SessionAction.NONE
    assert session.tick(10.0, has_pending_text=False).action is SessionAction.ENTER_OFF


def test_stop_enters_off() -> None:
    session = new_session()
    session.on_stt_wake(5.0)

    decision = session.on_stop(6.0, "stop word detected")

    assert decision.action is SessionAction.ENTER_OFF
    assert session.state is ListenState.OFF
