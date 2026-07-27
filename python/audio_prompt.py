from __future__ import annotations

import os
import signal
import subprocess
from enum import Enum
from pathlib import Path
from typing import Protocol, Sequence


class PromptStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class PromptPlayer(Protocol):
    def start(self, audio_path: Path, *, now: float) -> None: ...

    def poll(self, *, now: float) -> PromptStatus: ...

    def close(self) -> None: ...


class TapovoiceFilePromptPlayer:
    def __init__(self, command: Sequence[str], *, timeout_sec: float) -> None:
        if not command:
            raise ValueError("tapovoice command must not be empty")
        if timeout_sec <= 0:
            raise ValueError("prompt timeout must be greater than zero")
        self._command = tuple(command)
        self._timeout_sec = timeout_sec
        self._process: subprocess.Popen[bytes] | None = None
        self._started_at = 0.0
        self._terminal_status = PromptStatus.IDLE

    def start(self, audio_path: Path, *, now: float) -> None:
        if self._process is not None and self._process.poll() is None:
            raise RuntimeError("wake prompt is already running")
        self._process = subprocess.Popen(
            [*self._command, "-i", str(audio_path.resolve())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        self._started_at = now
        self._terminal_status = PromptStatus.RUNNING

    def poll(self, *, now: float) -> PromptStatus:
        process = self._process
        if process is None:
            return self._terminal_status

        return_code = process.poll()
        if return_code is None:
            if now - self._started_at < self._timeout_sec:
                return PromptStatus.RUNNING
            self._terminate_process_group(process)
            self._process = None
            self._terminal_status = PromptStatus.TIMED_OUT
            return self._terminal_status

        self._process = None
        self._terminal_status = (
            PromptStatus.SUCCEEDED if return_code == 0 else PromptStatus.FAILED
        )
        return self._terminal_status

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is not None and process.poll() is None:
            self._terminate_process_group(process)
        self._terminal_status = PromptStatus.IDLE

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=0.5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=0.5)
