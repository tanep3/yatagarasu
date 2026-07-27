from __future__ import annotations

from pathlib import Path

import audio_prompt
from audio_prompt import PromptStatus, TapovoiceFilePromptPlayer


class FakeProcess:
    def __init__(self) -> None:
        self.pid = 123
        self.return_code: int | None = None

    def poll(self) -> int | None:
        return self.return_code

    def wait(self, timeout: float) -> int:
        del timeout
        self.return_code = -15
        return self.return_code


def test_prompt_player_starts_without_waiting(
    monkeypatch,
    tmp_path: Path,
) -> None:
    process = FakeProcess()
    captured: dict[str, object] = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return process

    monkeypatch.setattr(audio_prompt.subprocess, "Popen", fake_popen)
    audio_path = tmp_path / "hai.mp3"
    audio_path.write_bytes(b"audio")
    player = TapovoiceFilePromptPlayer(["tapovoice"], timeout_sec=2.0)

    player.start(audio_path, now=1.0)

    assert captured["argv"] == ["tapovoice", "-i", str(audio_path.resolve())]
    assert player.poll(now=1.1) is PromptStatus.RUNNING


def test_prompt_player_reports_success(monkeypatch, tmp_path: Path) -> None:
    process = FakeProcess()
    monkeypatch.setattr(audio_prompt.subprocess, "Popen", lambda *args, **kwargs: process)
    audio_path = tmp_path / "hai.mp3"
    audio_path.write_bytes(b"audio")
    player = TapovoiceFilePromptPlayer(["tapovoice"], timeout_sec=2.0)
    player.start(audio_path, now=1.0)
    process.return_code = 0

    assert player.poll(now=1.1) is PromptStatus.SUCCEEDED


def test_prompt_player_times_out(monkeypatch, tmp_path: Path) -> None:
    process = FakeProcess()
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(audio_prompt.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        audio_prompt.os,
        "killpg",
        lambda pid, sig: killed.append((pid, sig)),
    )
    audio_path = tmp_path / "hai.mp3"
    audio_path.write_bytes(b"audio")
    player = TapovoiceFilePromptPlayer(["tapovoice"], timeout_sec=2.0)
    player.start(audio_path, now=1.0)

    assert player.poll(now=3.0) is PromptStatus.TIMED_OUT
    assert killed
