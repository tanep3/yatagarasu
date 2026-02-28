#!/usr/bin/env python3
"""
listend.py

RTSP音声を常時監視し、以下を実行する。
- Silero VAD で有音/無音判定
- STTバックエンド（faster-whisper / ReazonSpeech k2）で発話セグメントを文字起こし
- OFF時は文字起こし結果の wake word 検出で ON に遷移
- ON時は stop word 検出で OFF に遷移
- ON時は無音 3 秒（デフォルト）で 1 ターンを確定して yatagarasu に渡す
- ON時は無音 30 秒（デフォルト）で OFF に戻る
"""

from __future__ import annotations

import logging
import math
import os
import re
import select
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable

import numpy as np
import torch
from faster_whisper import WhisperModel
from silero_vad import get_speech_timestamps, load_silero_vad

DEFAULT_AUDIO_FILTER = "highpass=f=120,lowpass=f=5000"
DEFAULT_SEGMENT_END_SILENCE_CHUNKS = 5
# VADが一時的にFalseになっても発話継続とみなす猶予チャンク数
DEFAULT_VAD_HANGOVER_CHUNKS = 6
# これ未満の音量セグメントは文字起こししない（無音ハルシネーション抑制）
DEFAULT_MIN_TRANSCRIBE_RMS_DBFS = -50.0
# ReazonSpeech k2 は ~30秒程度が入力上限のため、長尺は分割処理する。
DEFAULT_REAZON_MAX_SEGMENT_SEC = 28.0

# auto モードでのトランスポート試行順序（go2rtc は TCP のみサポートが一般的）
_AUTO_TRANSPORT_ORDER = ("tcp", "udp")
# ffmpeg 起動後、最初のデータを待つタイムアウト（秒）
_INITIAL_DATA_PROBE_SEC = 5.0


class ListenState(str, Enum):
    OFF = "OFF"
    WAKE_DETECTED = "WAKE_DETECTED"
    ON = "ON"


def normalize_stt_backend(value: str) -> str:
    raw = value.strip().lower()
    mapping = {
        "faster-whisper": "faster-whisper",
        "faster_whisper": "faster-whisper",
        "whisper": "faster-whisper",
        "reazonspeech-k2": "reazonspeech-k2",
        "reazonspeech_k2": "reazonspeech-k2",
        "reazonspeech": "reazonspeech-k2",
        "reazon": "reazonspeech-k2",
        "k2": "reazonspeech-k2",
    }
    return mapping.get(raw, "")


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if not value:
        return value
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        logging.warning(".env not found: %s", env_path)
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = _strip_quotes(value)
        if key and key not in os.environ:
            os.environ[key] = value


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logging.warning("Invalid int env %s=%s; fallback=%s", name, value, default)
        return default


def env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        logging.warning("Invalid float env %s=%s; fallback=%s", name, value, default)
        return default


def env_csv(name: str, default: Iterable[str]) -> tuple[str, ...]:
    value = os.getenv(name, "").strip()
    if not value:
        return tuple(default)
    normalized = value.replace("、", ",")
    parts = [part.strip() for part in normalized.split(",")]
    filtered = [part for part in parts if part]
    if not filtered:
        return tuple(default)
    return tuple(filtered)


def resolve_workspace_path() -> Path:
    raw = os.getenv("YATAGARASU_CWD", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def build_rtsp_url_from_legacy_env() -> str:
    host = os.getenv("GO2RTC_HOST", "").strip()
    stream = os.getenv("STREAM", "").strip()
    if not host or not stream:
        return ""
    port = os.getenv("GO2RTC_RTSP_PORT", "8554").strip() or "8554"
    if host.startswith("rtsp://"):
        return f"{host.rstrip('/')}/{stream}"
    return f"rtsp://{host}:{port}/{stream}"


@dataclass(frozen=True)
class ListendSettings:
    workspace_path: Path
    rtsp_url: str
    rtsp_transport: str
    stt_backend: str
    stt_language: str
    whisper_model: str
    whisper_device: str
    whisper_compute_type: str
    whisper_language: str
    whisper_beam_size: int
    reazon_device: str
    reazon_precision: str
    reazon_language: str
    wake_words: tuple[str, ...]
    wake_prompt_word: str
    stop_words: tuple[str, ...]
    vad_threshold: float
    min_segment_sec: float
    off_transcribe_cooldown_sec: float
    silence_timeout_sec: float
    session_end_silence_sec: float
    chunk_ms: int
    segment_end_silence_chunks: int
    sample_rate: int
    channels: int
    dispatch_cmd: str
    dispatch_timeout_sec: float
    wake_ack_word: str
    standby_word: str
    wake_ack_speaker_id: str
    wake_ack_timeout_sec: float
    wake_ack_zunda_cmd: str
    wake_ack_tapovoice_cmd: str
    ffmpeg_bin: str
    reconnect_delay_sec: float
    max_reconnect_attempts: int
    no_data_timeout_sec: float
    heartbeat_sec: float
    log_level: str

    @classmethod
    def from_env(cls) -> "ListendSettings":
        workspace_path = resolve_workspace_path()
        load_env_file(workspace_path / ".env")

        rtsp_url = os.getenv("LISTEND_RTSP_URL", "").strip()
        if not rtsp_url:
            rtsp_url = build_rtsp_url_from_legacy_env()
        if not rtsp_url:
            raise ValueError(
                "LISTEND_RTSP_URL is required. "
                "Or set GO2RTC_HOST / GO2RTC_RTSP_PORT / STREAM in .env."
            )

        rtsp_transport = os.getenv("LISTEND_RTSP_TRANSPORT", "auto").strip().lower()
        if rtsp_transport not in {"auto", "tcp", "udp", "udp_multicast", "http", "https"}:
            logging.warning(
                "Invalid LISTEND_RTSP_TRANSPORT=%s; fallback=auto",
                rtsp_transport,
            )
            rtsp_transport = "auto"

        stt_backend = normalize_stt_backend(
            os.getenv("LISTEND_STT_BACKEND", "faster-whisper")
        )
        if not stt_backend:
            logging.warning(
                "Invalid LISTEND_STT_BACKEND=%s; fallback=faster-whisper",
                os.getenv("LISTEND_STT_BACKEND", "").strip(),
            )
            stt_backend = "faster-whisper"

        wake_words = env_csv("LISTEND_WAKE_WORDS", ())
        if not wake_words:
            raise ValueError(
                "LISTEND_WAKE_WORDS is required "
                "(comma-separated words, e.g. ヤタガラス)."
            )

        wake_prompt_word = os.getenv("LISTEND_WAKE_PROMPT_WORD", "はい").strip()

        stop_words = env_csv("LISTEND_STOP_WORDS", ())
        if not stop_words:
            stop_words = env_csv("LISTEND_SLEEP_WORDS", ())
        if not stop_words:
            raise ValueError(
                "LISTEND_STOP_WORDS is required "
                "(comma-separated words, e.g. ストップ)."
            )

        dispatch_cmd = os.getenv("LISTEND_DISPATCH_CMD", "").strip()
        if not dispatch_cmd:
            dispatch_cmd = str((workspace_path.parent / "bin" / "yatagarasu").resolve())

        wake_ack_word = os.getenv("LISTEND_WAKE_ACK_WORD", "").strip()
        standby_word = os.getenv("LISTEND_STANDBY_WORD", "待機します。").strip()
        wake_ack_speaker_id = (
            os.getenv("LISTEND_WAKE_ACK_SPEAKER_ID", "").strip()
            or os.getenv("SPEAKER_ID", "").strip()
            or "68"
        )
        wake_ack_zunda_cmd = os.getenv("LISTEND_WAKE_ACK_ZUNDA_CMD", "").strip()
        if not wake_ack_zunda_cmd:
            wake_ack_zunda_cmd = str((workspace_path.parent / "bin" / "zunda").resolve())
        wake_ack_tapovoice_cmd = os.getenv("LISTEND_WAKE_ACK_TAPOVOICE_CMD", "").strip()
        if not wake_ack_tapovoice_cmd:
            wake_ack_tapovoice_cmd = str(
                (workspace_path.parent / "bin" / "tapovoice").resolve()
            )

        if os.getenv("LISTEND_SEGMENT_END_SILENCE_CHUNKS", "").strip():
            logging.warning(
                "LISTEND_SEGMENT_END_SILENCE_CHUNKS is ignored; "
                "using code constant DEFAULT_SEGMENT_END_SILENCE_CHUNKS=%d",
                DEFAULT_SEGMENT_END_SILENCE_CHUNKS,
            )

        stt_language = os.getenv("LISTEND_STT_LANGUAGE", "").strip().lower()
        if not stt_language:
            stt_language = os.getenv("LISTEND_WHISPER_LANGUAGE", "ja").strip().lower()
        if not stt_language:
            stt_language = "ja"

        whisper_language = os.getenv("LISTEND_WHISPER_LANGUAGE", "").strip().lower()
        if not whisper_language:
            whisper_language = stt_language

        reazon_language = os.getenv("LISTEND_REAZON_LANGUAGE", "").strip().lower()
        if not reazon_language:
            reazon_language = stt_language
        if reazon_language == "en":
            logging.warning(
                "LISTEND_REAZON_LANGUAGE=en is mapped to ja-en "
                "(k2-v2 is Japanese/bilingual)."
            )
            reazon_language = "ja-en"
        if reazon_language not in {"ja", "ja-en"}:
            logging.warning(
                "Invalid LISTEND_REAZON_LANGUAGE=%s; fallback=ja",
                reazon_language,
            )
            reazon_language = "ja"

        reazon_precision = (
            os.getenv("LISTEND_REAZON_PRECISION", "int8").strip().lower() or "int8"
        )
        if reazon_precision not in {"int8", "fp16", "fp32"}:
            logging.warning(
                "Invalid LISTEND_REAZON_PRECISION=%s; fallback=int8",
                reazon_precision,
            )
            reazon_precision = "int8"

        return cls(
            workspace_path=workspace_path,
            rtsp_url=rtsp_url,
            rtsp_transport=rtsp_transport,
            stt_backend=stt_backend,
            stt_language=stt_language,
            whisper_model=os.getenv("LISTEND_WHISPER_MODEL", "base").strip() or "base",
            whisper_device=os.getenv("LISTEND_WHISPER_DEVICE", "cpu").strip() or "cpu",
            whisper_compute_type=os.getenv("LISTEND_WHISPER_COMPUTE_TYPE", "int8").strip()
            or "int8",
            whisper_language=whisper_language or "ja",
            whisper_beam_size=max(1, env_int("LISTEND_WHISPER_BEAM_SIZE", 1)),
            reazon_device=os.getenv("LISTEND_REAZON_DEVICE", "cpu").strip() or "cpu",
            reazon_precision=reazon_precision,
            reazon_language=reazon_language,
            wake_words=wake_words,
            wake_prompt_word=wake_prompt_word,
            stop_words=stop_words,
            vad_threshold=env_float("LISTEND_VAD_THRESHOLD", 0.5),
            min_segment_sec=env_float("LISTEND_MIN_SEGMENT_SEC", 0.35),
            off_transcribe_cooldown_sec=env_float(
                "LISTEND_OFF_TRANSCRIBE_COOLDOWN_SEC", 0.0
            ),
            silence_timeout_sec=env_float("LISTEND_SILENCE_TIMEOUT_SEC", 30.0),
            session_end_silence_sec=env_float("LISTEND_SESSION_END_SILENCE_SEC", 3.0),
            chunk_ms=env_int("LISTEND_CHUNK_MS", 80),
            segment_end_silence_chunks=DEFAULT_SEGMENT_END_SILENCE_CHUNKS,
            sample_rate=env_int("LISTEND_SAMPLE_RATE", 16000),
            channels=env_int("LISTEND_CHANNELS", 1),
            dispatch_cmd=dispatch_cmd,
            dispatch_timeout_sec=env_float("LISTEND_DISPATCH_TIMEOUT_SEC", 20.0),
            wake_ack_word=wake_ack_word,
            standby_word=standby_word,
            wake_ack_speaker_id=wake_ack_speaker_id,
            wake_ack_timeout_sec=env_float("LISTEND_WAKE_ACK_TIMEOUT_SEC", 8.0),
            wake_ack_zunda_cmd=wake_ack_zunda_cmd,
            wake_ack_tapovoice_cmd=wake_ack_tapovoice_cmd,
            ffmpeg_bin=os.getenv("LISTEND_FFMPEG_BIN", "ffmpeg").strip() or "ffmpeg",
            reconnect_delay_sec=env_float("LISTEND_RECONNECT_DELAY_SEC", 3.0),
            max_reconnect_attempts=env_int("LISTEND_MAX_RECONNECT_ATTEMPTS", 0),
            no_data_timeout_sec=env_float("LISTEND_NO_DATA_TIMEOUT_SEC", 10.0),
            heartbeat_sec=env_float("LISTEND_HEARTBEAT_SEC", 5.0),
            log_level=os.getenv("LISTEND_LOG_LEVEL", "INFO").strip().upper() or "INFO",
        )


class ListendService:
    def __init__(self, settings: ListendSettings) -> None:
        self.settings = settings
        self.state = ListenState.OFF
        self.stop_requested = False

        self.in_segment = False
        self.trailing_silence_chunks = 0
        self.segment_buffer = bytearray()
        self.vad_hangover_remaining = 0

        self.last_voice_at = time.monotonic()
        self.session_text_chunks: list[str] = []
        self.wake_ack_pending = False
        self.last_off_transcribe_at = 0.0
        self.chunk_index = 0

        self.vad_model = load_silero_vad()
        self.whisper_model: WhisperModel | None = None
        self.reazon_model: object | None = None
        self.reazon_audio_from_numpy: object | None = None
        self.reazon_transcribe: object | None = None
        self._init_stt_backend()

    def _init_stt_backend(self) -> None:
        if self.settings.stt_backend == "faster-whisper":
            self._init_whisper_backend()
            return
        if self.settings.stt_backend == "reazonspeech-k2":
            self._init_reazonspeech_backend()
            return
        raise RuntimeError(f"unsupported STT backend: {self.settings.stt_backend}")

    def _init_whisper_backend(self) -> None:
        self.whisper_model = WhisperModel(
            self.settings.whisper_model,
            device=self.settings.whisper_device,
            compute_type=self.settings.whisper_compute_type,
        )

    def _init_reazonspeech_backend(self) -> None:
        try:
            from reazonspeech.k2.asr import audio_from_numpy, load_model, transcribe
        except Exception as exc:  # pragma: no cover - import可否は環境依存
            raise RuntimeError(
                "reazonspeech backend selected but module import failed. "
                "Install with: uv pip install '<ReazonSpeech repo>/pkg/k2-asr'"
            ) from exc

        self.reazon_audio_from_numpy = audio_from_numpy
        self.reazon_transcribe = transcribe
        self.reazon_model = load_model(
            device=self.settings.reazon_device,
            precision=self.settings.reazon_precision,
            language=self.settings.reazon_language,
        )

    def request_stop(self) -> None:
        self.stop_requested = True

    def _resolve_transports(self) -> list[str]:
        """auto モードの場合にフォールバック候補リストを返す。
        明示指定の場合はそれだけを返す。
        """
        if self.settings.rtsp_transport == "auto":
            return list(_AUTO_TRANSPORT_ORDER)
        return [self.settings.rtsp_transport]

    def run(self) -> int:
        chunk_samples = int(self.settings.sample_rate * self.settings.chunk_ms / 1000)
        if chunk_samples <= 0:
            logging.error("Invalid chunk size. LISTEND_CHUNK_MS=%s", self.settings.chunk_ms)
            return 2
        chunk_bytes = chunk_samples * 2 * self.settings.channels
        read_unit = max(1024, chunk_bytes // 2)

        reconnect_attempts = 0
        while not self.stop_requested:
            # --- ffmpeg 起動（auto ならフォールバック試行） ---
            ffmpeg_proc: subprocess.Popen[bytes] | None = None
            ffmpeg_stderr_log: Path | None = None
            active_transport: str = self.settings.rtsp_transport

            transports = self._resolve_transports()
            for idx, transport in enumerate(transports):
                try:
                    ffmpeg_proc, ffmpeg_stderr_log = self._start_ffmpeg(
                        transport_override=transport,
                    )
                except FileNotFoundError:
                    logging.error("ffmpeg not found: %s", self.settings.ffmpeg_bin)
                    return 2
                except Exception as exc:
                    logging.error("failed to start ffmpeg: %s", exc)
                    return 2

                # 初期データ probe: 短時間でデータが来るか確認
                ok = self._probe_initial_data(ffmpeg_proc, ffmpeg_stderr_log)
                if ok:
                    active_transport = transport
                    break

                # probe 失敗 → 次のトランスポートを試す
                self._stop_ffmpeg(ffmpeg_proc)
                self._cleanup_temp_log(ffmpeg_stderr_log)
                ffmpeg_proc = None
                ffmpeg_stderr_log = None

                if idx < len(transports) - 1:
                    next_t = transports[idx + 1]
                    logging.info(
                        "transport %s failed, trying %s...",
                        transport,
                        next_t,
                    )
                else:
                    logging.warning(
                        "all transports exhausted (%s); will retry after delay",
                        ", ".join(transports),
                    )

            if ffmpeg_proc is None:
                # 全トランスポートが probe 失敗
                if self.stop_requested:
                    break
                reconnect_attempts += 1
                if (
                    self.settings.max_reconnect_attempts > 0
                    and reconnect_attempts > self.settings.max_reconnect_attempts
                ):
                    logging.error(
                        "exceeded max reconnect attempts: %s", reconnect_attempts
                    )
                    return 1
                logging.info(
                    "reconnecting in %.1fs...", self.settings.reconnect_delay_sec
                )
                time.sleep(self.settings.reconnect_delay_sec)
                continue

            # --- メインオーディオ読み取りループ ---
            try:
                read_buffer = bytearray()
                last_data_at = time.monotonic()
                last_heartbeat_at = last_data_at
                chunks_since_heartbeat = 0
                total_chunks = 0
                stdout_fd = ffmpeg_proc.stdout.fileno()
                os.set_blocking(stdout_fd, False)
                logging.info(
                    "audio read loop started fd=%s transport=%s",
                    stdout_fd,
                    active_transport,
                )
                while not self.stop_requested:
                    if ffmpeg_proc.poll() is not None:
                        raise RuntimeError(f"ffmpeg exited rc={ffmpeg_proc.returncode}")

                    ready, _, _ = select.select([stdout_fd], [], [], 0.5)
                    now = time.monotonic()

                    # --- ハートビート（データ有無にかかわらず定期出力）---
                    if now - last_heartbeat_at >= self.settings.heartbeat_sec:
                        logging.info(
                            "heartbeat: state=%s chunks=%d total=%d buffered=%d",
                            self.state,
                            chunks_since_heartbeat,
                            total_chunks,
                            len(read_buffer),
                        )
                        last_heartbeat_at = now
                        chunks_since_heartbeat = 0

                    if not ready:
                        if now - last_data_at >= self.settings.no_data_timeout_sec:
                            raise RuntimeError(
                                "audio timeout: no data for "
                                f"{self.settings.no_data_timeout_sec:.1f}s"
                            )
                        continue

                    try:
                        data = os.read(stdout_fd, read_unit)
                    except BlockingIOError:
                        continue
                    if not data:
                        if ffmpeg_proc.poll() is None:
                            # 稀に select 後にデータが取れないケースがあるため継続。
                            continue
                        # EOF。未処理バッファは破棄して再接続へ。
                        if read_buffer:
                            logging.debug(
                                "dropping partial audio buffer on EOF: %s bytes",
                                len(read_buffer),
                            )
                        raise RuntimeError("audio stream ended")

                    reconnect_attempts = 0
                    last_data_at = now
                    read_buffer.extend(data)

                    while len(read_buffer) >= chunk_bytes:
                        chunk = bytes(read_buffer[:chunk_bytes])
                        del read_buffer[:chunk_bytes]
                        self._process_chunk(chunk)
                        total_chunks += 1
                        chunks_since_heartbeat += 1
            except Exception as exc:
                if self.stop_requested:
                    break
                ffmpeg_hint = self._read_ffmpeg_stderr_tail(ffmpeg_stderr_log)
                if ffmpeg_hint:
                    logging.warning("audio loop interrupted: %s | ffmpeg=%s", exc, ffmpeg_hint)
                else:
                    logging.warning("audio loop interrupted: %s", exc)
            finally:
                self._stop_ffmpeg(ffmpeg_proc)
                self._cleanup_temp_log(ffmpeg_stderr_log)

            if self.stop_requested:
                break

            reconnect_attempts += 1
            if (
                self.settings.max_reconnect_attempts > 0
                and reconnect_attempts > self.settings.max_reconnect_attempts
            ):
                logging.error("exceeded max reconnect attempts: %s", reconnect_attempts)
                return 1

            logging.info("reconnecting in %.1fs...", self.settings.reconnect_delay_sec)
            time.sleep(self.settings.reconnect_delay_sec)

        self._flush_before_exit()
        return 0

    def _start_ffmpeg(
        self,
        transport_override: str | None = None,
    ) -> tuple[subprocess.Popen[bytes], Path | None]:
        """ffmpeg プロセスを起動する。

        Args:
            transport_override: 指定すると rtsp_transport 設定を上書きして
                ``-rtsp_transport <value>`` を付与する。
                ``None`` の場合は設定値に従う（auto なら付与しない）。
        """
        stderr_log_path: Path | None = None
        stderr_sink: object = subprocess.DEVNULL
        try:
            stderr_log = tempfile.NamedTemporaryFile(
                mode="wb",
                prefix="listend_ffmpeg_",
                suffix=".log",
                delete=False,
            )
            stderr_log_path = Path(stderr_log.name)
            stderr_sink = stderr_log
        except Exception:
            stderr_log = None

        transport = transport_override or self.settings.rtsp_transport

        cmd = [
            self.settings.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
        ]
        if transport != "auto":
            cmd.extend(["-rtsp_transport", transport])
        cmd.extend(
            [
                "-i",
                self.settings.rtsp_url,
                "-vn",
                "-af",
                DEFAULT_AUDIO_FILTER,
                "-f",
                "s16le",
                "-ac",
                str(self.settings.channels),
                "-ar",
                str(self.settings.sample_rate),
                "pipe:1",
            ]
        )
        logging.info("starting ffmpeg: %s", " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=stderr_sink,
                bufsize=0,
            )
        finally:
            if "stderr_log" in locals() and stderr_log is not None:
                stderr_log.close()
        return proc, stderr_log_path

    def _probe_initial_data(
        self,
        proc: subprocess.Popen[bytes],
        stderr_log: Path | None,
        timeout_sec: float = _INITIAL_DATA_PROBE_SEC,
    ) -> bool:
        """ffmpeg 起動直後に最初のデータが来るか確認する。

        データが来ればTrue、タイムアウトやプロセス終了ならFalseを返す。
        失敗時は stderr の内容をログに出力する。
        """
        stdout_fd = proc.stdout.fileno()
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                hint = self._read_ffmpeg_stderr_tail(stderr_log)
                logging.warning(
                    "ffmpeg exited during probe rc=%s%s",
                    proc.returncode,
                    f" | {hint}" if hint else "",
                )
                return False
            remaining = max(0.1, deadline - time.monotonic())
            ready, _, _ = select.select([stdout_fd], [], [], min(remaining, 0.5))
            if ready:
                # ここで read すると PCM を1byte消費してしまい、
                # 16bit 境界が崩れて以後の音声が壊れるため read しない。
                logging.debug("initial data probe succeeded")
                return True
        # タイムアウト
        hint = self._read_ffmpeg_stderr_tail(stderr_log)
        logging.warning(
            "initial data probe timed out (%.1fs)%s",
            timeout_sec,
            f" | ffmpeg: {hint}" if hint else "",
        )
        return False

    @staticmethod
    def _stop_ffmpeg(proc: subprocess.Popen[bytes]) -> None:
        if proc.poll() is not None:
            return
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=1)

    @staticmethod
    def _read_ffmpeg_stderr_tail(log_path: Path | None, max_lines: int = 3) -> str:
        if log_path is None or not log_path.exists():
            return ""
        try:
            lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            return ""
        lines = [line.strip() for line in lines if line.strip()]
        if not lines:
            return ""
        return " | ".join(lines[-max_lines:])

    @staticmethod
    def _cleanup_temp_log(log_path: Path | None) -> None:
        if log_path is None:
            return
        try:
            log_path.unlink(missing_ok=True)
        except Exception:
            pass

    def _process_chunk(self, chunk: bytes) -> None:
        pcm = np.frombuffer(chunk, dtype=np.int16)
        if pcm.size == 0:
            return

        now = time.monotonic()
        has_speech = self._has_speech(pcm)
        logging.debug(
            "chunk pcm=%d speech=%s in_seg=%s hangover=%d",
            pcm.size,
            has_speech,
            self.in_segment,
            self.vad_hangover_remaining,
        )

        if has_speech:
            self.last_voice_at = now
            self.in_segment = True
            self.trailing_silence_chunks = 0
            self.segment_buffer.extend(chunk)
            self.vad_hangover_remaining = DEFAULT_VAD_HANGOVER_CHUNKS
            return

        if self.in_segment:
            if self.vad_hangover_remaining > 0:
                self.vad_hangover_remaining -= 1
                self.last_voice_at = now
                self.trailing_silence_chunks = 0
                self.segment_buffer.extend(chunk)
                logging.debug(
                    "chunk treated as speech by hangover remaining=%d",
                    self.vad_hangover_remaining,
                )
                return
            self.trailing_silence_chunks += 1
            self.segment_buffer.extend(chunk)
            if self.trailing_silence_chunks >= self.settings.segment_end_silence_chunks:
                self._finalize_segment()
            return

        if self.state == ListenState.ON:
            self._handle_on_silence(now)

    def _handle_on_silence(self, now: float) -> None:
        idle_sec = now - self.last_voice_at

        if self.session_text_chunks and idle_sec >= self.settings.session_end_silence_sec:
            self._dispatch_session(
                reason=(
                    f"session end silence ({idle_sec:.1f}s >= "
                    f"{self.settings.session_end_silence_sec:.1f}s)"
                )
            )

        # セッションが空（ウェイク後無発話）またはタイムアウトでOFFに戻る
        if not self.session_text_chunks or idle_sec >= self.settings.silence_timeout_sec:
            self._set_state(
                ListenState.OFF,
                reason=(
                    f"cancel session (idle_sec={idle_sec:.1f}s "
                    f"chunks={len(self.session_text_chunks)})"
                ),
            )

    def _finalize_segment(self) -> None:
        raw = bytes(self.segment_buffer)
        self.segment_buffer.clear()
        self.in_segment = False
        self.trailing_silence_chunks = 0
        self.vad_hangover_remaining = 0

        duration_sec = self._segment_duration_sec(raw)
        if duration_sec < self.settings.min_segment_sec:
            if self._debug_enabled():
                logging.debug(
                    f"[listend chunk-skip] reason=short-segment duration={duration_sec:.2f}s "
                    f"min={self.settings.min_segment_sec:.2f}s"
                )
            logging.debug(
                "skip short segment: %.3fs < %.3fs",
                duration_sec,
                self.settings.min_segment_sec,
            )
            return

        rms_dbfs = self._segment_rms_dbfs(raw)
        if rms_dbfs < DEFAULT_MIN_TRANSCRIBE_RMS_DBFS:
            if self._debug_enabled():
                logging.debug(
                    "[listend chunk-skip] reason=low-rms rms_dbfs=%.1f threshold=%.1f",
                    rms_dbfs,
                    DEFAULT_MIN_TRANSCRIBE_RMS_DBFS,
                )
            return

        now = time.monotonic()
        if (
            self.state == ListenState.OFF
            and self.settings.off_transcribe_cooldown_sec > 0
            and (now - self.last_off_transcribe_at)
            < self.settings.off_transcribe_cooldown_sec
        ):
            if self._debug_enabled():
                remain = self.settings.off_transcribe_cooldown_sec - (
                    now - self.last_off_transcribe_at
                )
                logging.debug(
                    f"[listend chunk-skip] reason=off-cooldown remaining={max(0.0, remain):.2f}s",
                )
            logging.debug(
                "skip off transcribe by cooldown: %.3fs remaining",
                self.settings.off_transcribe_cooldown_sec - (now - self.last_off_transcribe_at),
            )
            return

        transcription = self._transcribe(raw)
        if not transcription:
            if self._debug_enabled():
                logging.debug("[listend chunk-empty] transcription is empty")
            return

        self.chunk_index += 1
        wake_hit, wake_word = self._match_word(transcription, self.settings.wake_words)
        stop_hit, stop_word = self._match_word(transcription, self.settings.stop_words)
        self._emit_chunk_debug(
            self.state,
            transcription,
            duration_sec,
            wake_hit,
            wake_word,
            stop_hit,
            stop_word,
        )

        logging.info("segment transcription: %s", transcription)

        if self.state == ListenState.OFF:
            self.last_off_transcribe_at = now
            if wake_hit:
                # 自分の発話したウェイクワードのみの場合は無視（ループ防止）
                without_wake = self._remove_words(transcription, self.settings.wake_words)
                without_wake_normalized = " ".join(without_wake.split()).strip()
                if not without_wake_normalized:
                    logging.info("wake word detected but transcription contains only wake words; ignoring to prevent loop")
                    return
                # ウェイクワード検出時はACK発話してディスパッチ
                # transcriptionを保持して、wake word検出時はACK発話してディスパッチ
                logging.info("wake word detected in OFF segment; dispatching with text")
                self._set_state(ListenState.ON, "wake word detected in OFF segment")
                self._append_session_text(transcription)
                # 無音検出時に即時ディスパッチするため、短いタイマー設定
                self.last_voice_at = time.monotonic() - self.settings.session_end_silence_sec + 0.5
            return

        if stop_hit:
            # stop word検出時はキャンセルしてOFFに戻る（ディスパッチしない）
            self._set_state(ListenState.OFF, reason="stop word detected (cancel)")
            return

        if wake_hit:
            # 一時対応:
            # ON中の再ウェイクでは確認音声を鳴らさない。
            # 連続発話中のストリーム中断頻度を下げるため。
            logging.info("wake word detected while ON; wake ack suppressed (temporary)")

        self._append_session_text(transcription)

    def _flush_before_exit(self) -> None:
        if self.in_segment and self.segment_buffer:
            self._finalize_segment()
        if self.state == ListenState.ON and self.session_text_chunks:
            self._dispatch_session(reason="shutdown flush")

    def _set_state(self, new_state: ListenState, reason: str) -> None:
        old_state = self.state
        self.state = new_state

        if new_state == ListenState.ON:
            self.session_text_chunks.clear()
            if old_state != new_state:
                if self._play_wake_ack():
                    self.wake_ack_pending = False
                else:
                    self.wake_ack_pending = True
            # ON遷移時の副作用（wake ack再生など）完了後を
            # 無音タイマーの起点にする。
            self.last_voice_at = time.monotonic()

        if new_state == ListenState.OFF:
            self.in_segment = False
            self.trailing_silence_chunks = 0
            self.segment_buffer.clear()
            self.vad_hangover_remaining = 0
            self.session_text_chunks.clear()
            self.wake_ack_pending = False
            if old_state != new_state:
                # ストップワード検出時のみ「ストップ」を発話（無音タイムアウト時は発話しない）
                if "stop word detected" in reason:
                    self._play_standby_word()

        if old_state != new_state:
            logging.info("state transition: %s -> %s (%s)", old_state, new_state, reason)
        else:
            logging.info("state stayed: %s (%s)", new_state, reason)

    def _append_session_text(self, text: str) -> None:
        normalized = " ".join(text.split()).strip()
        if normalized:
            self.session_text_chunks.append(normalized)

    def _dispatch_session(self, reason: str) -> None:
        text = " ".join(self.session_text_chunks).strip()
        self.session_text_chunks.clear()
        if not text:
            return
        if self.wake_ack_pending:
            if self._play_wake_ack():
                self.wake_ack_pending = False
            else:
                logging.warning(
                    "wake ack was not completed; will retry before next dispatch"
                )
        logging.info("dispatch session (%s): %s", reason, text)
        self._dispatch(text)

    def _emit_chunk_debug(
        self,
        state: ListenState,
        transcription: str,
        duration_sec: float,
        wake_hit: bool,
        wake_word: str | None,
        stop_hit: bool,
        stop_word: str | None,
    ) -> None:
        if not self._debug_enabled():
            return
        msg = (
            f"[listend chunk#{self.chunk_index:04d}] "
            f"state={state} duration={duration_sec:.2f}s text={transcription}"
        )
        logging.debug(msg)

        norm_text = self._normalize_text_for_match(transcription)
        wake_norm = [self._normalize_text_for_match(word) for word in self.settings.wake_words]
        stop_norm = [self._normalize_text_for_match(word) for word in self.settings.stop_words]
        detail = (
            f"[listend match#{self.chunk_index:04d}] "
            f"state={state} normalized_text={norm_text} "
            f"wake_hit={wake_hit} wake_word={wake_word or '-'} wake_words={wake_norm} "
            f"stop_hit={stop_hit} stop_word={stop_word or '-'} stop_words={stop_norm}"
        )
        logging.debug(detail)

    @staticmethod
    def _debug_enabled() -> bool:
        return logging.getLogger().isEnabledFor(logging.DEBUG)

    def _has_speech(self, pcm: np.ndarray) -> bool:
        audio = pcm.astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio)
        # ストリーミングVAD: モデルを直接呼び出して確率値を取得。
        # get_speech_timestamps は min_speech_duration_ms=250ms がデフォルトで
        # 80ms チャンクでは音声を検出できないため使用しない。
        try:
            speech_prob = self.vad_model(
                tensor, self.settings.sample_rate
            ).item()
        except Exception:
            # フォールバック: get_speech_timestamps を使用
            try:
                timestamps = get_speech_timestamps(
                    tensor,
                    self.vad_model,
                    sampling_rate=self.settings.sample_rate,
                    threshold=self.settings.vad_threshold,
                    min_speech_duration_ms=0,
                )
            except TypeError:
                timestamps = get_speech_timestamps(
                    tensor,
                    self.vad_model,
                    sampling_rate=self.settings.sample_rate,
                )
            return bool(timestamps)
        return speech_prob >= self.settings.vad_threshold

    def _transcribe(self, raw_audio: bytes) -> str:
        if self.settings.stt_backend == "reazonspeech-k2":
            return self._transcribe_reazonspeech(raw_audio)
        return self._transcribe_faster_whisper(raw_audio)

    def _transcribe_faster_whisper(self, raw_audio: bytes) -> str:
        if not raw_audio:
            return ""
        audio = np.frombuffer(raw_audio, dtype=np.int16)
        if audio.size == 0:
            return ""
        audio_f32 = audio.astype(np.float32) / 32768.0
        kwargs: dict[str, object] = {
            "beam_size": max(1, self.settings.whisper_beam_size),
            "condition_on_previous_text": False,
        }
        language = self.settings.whisper_language.strip().lower()
        if language and language != "auto":
            kwargs["language"] = language

        # Pass 1: 標準寄り。まずは誤認識を抑える。
        kwargs["no_speech_threshold"] = 0.70
        kwargs["log_prob_threshold"] = -1.5
        kwargs["compression_ratio_threshold"] = 2.8
        text = self._run_transcribe(audio_f32, kwargs)
        if text:
            return text

        # Pass 2: 空結果時のみ、やや緩い条件で再試行。
        # OFF状態では wake/stop語を hotwords として補助する。
        retry = dict(kwargs)
        retry["beam_size"] = max(2, self.settings.whisper_beam_size)
        retry["best_of"] = max(5, self.settings.whisper_beam_size)
        retry["temperature"] = [0.0, 0.2, 0.4, 0.6]
        retry["no_speech_threshold"] = 0.85
        retry["log_prob_threshold"] = -2.5
        retry["compression_ratio_threshold"] = 4.0
        if self.state == ListenState.OFF:
            hotwords = self._build_hotwords_for_whisper()
            if hotwords:
                retry["hotwords"] = hotwords
        text = self._run_transcribe(audio_f32, retry)
        if text and self._debug_enabled():
            logging.debug("transcribe recovered by permissive retry")
        return text

    def _transcribe_reazonspeech(self, raw_audio: bytes) -> str:
        if not raw_audio:
            return ""
        audio_i16 = np.frombuffer(raw_audio, dtype=np.int16)
        if audio_i16.size == 0:
            return ""
        audio_f32 = audio_i16.astype(np.float32) / 32768.0

        max_samples = int(DEFAULT_REAZON_MAX_SEGMENT_SEC * self.settings.sample_rate)
        if max_samples <= 0 or audio_f32.size <= max_samples:
            return self._run_reazonspeech_transcribe(audio_f32)

        logging.debug(
            "reazonspeech split: %.2fs by %.2fs",
            audio_f32.size / float(self.settings.sample_rate),
            DEFAULT_REAZON_MAX_SEGMENT_SEC,
        )
        texts: list[str] = []
        start = 0
        while start < audio_f32.size:
            end = min(audio_f32.size, start + max_samples)
            chunk_text = self._run_reazonspeech_transcribe(audio_f32[start:end])
            if chunk_text:
                texts.append(chunk_text)
            start = end
        return " ".join(texts).strip()

    def _run_reazonspeech_transcribe(self, audio_f32: np.ndarray) -> str:
        if audio_f32.size == 0:
            return ""
        if (
            self.reazon_model is None
            or self.reazon_audio_from_numpy is None
            or self.reazon_transcribe is None
        ):
            logging.error("reazonspeech backend is not initialized")
            return ""
        try:
            audio_data = self.reazon_audio_from_numpy(audio_f32, self.settings.sample_rate)
            result = self.reazon_transcribe(self.reazon_model, audio_data)
        except Exception as exc:
            logging.warning("reazonspeech transcribe failed: %s", exc)
            return ""
        text = getattr(result, "text", "")
        if text is None:
            return ""
        return str(text).strip()

    def _run_transcribe(self, audio_f32: np.ndarray, kwargs: dict[str, object]) -> str:
        if self.whisper_model is None:
            logging.error("faster-whisper backend is not initialized")
            return ""

        # initial_promptでウェイクワードをモデルに伝えて検出率向上
        if self.settings.wake_words and "initial_prompt" not in kwargs:
            wake_prompt = "、".join(self.settings.wake_words)
            kwargs["initial_prompt"] = f"次の単語を聞き取ってください: {wake_prompt}"

        segments, _ = self.whisper_model.transcribe(audio_f32, **kwargs)
        texts = [
            segment.text.strip()
            for segment in segments
            if segment.text and segment.text.strip()
        ]
        return " ".join(texts).strip()

    def _build_hotwords_for_whisper(self) -> str:
        ordered: list[str] = []
        seen: set[str] = set()
        for word in (*self.settings.wake_words, *self.settings.stop_words):
            w = word.strip()
            if not w:
                continue
            if w in seen:
                continue
            seen.add(w)
            ordered.append(w)
        return ",".join(ordered)

    def _match_word(self, text: str, words: tuple[str, ...]) -> tuple[bool, str | None]:
        if not text:
            return False, None
        norm_text = self._normalize_text_for_match(text)
        for word in words:
            norm_word = self._normalize_text_for_match(word)
            if norm_word and norm_word in norm_text:
                logging.info("keyword matched: raw=%s normalized=%s", word, norm_word)
                return True, word
        return False, None

    @staticmethod
    def _remove_words(text: str, words: tuple[str, ...]) -> str:
        result = text
        for word in words:
            if word:
                result = result.replace(word, "")
        return result

    def _segment_duration_sec(self, raw_audio: bytes) -> float:
        bytes_per_sample = 2 * max(self.settings.channels, 1)
        if bytes_per_sample <= 0 or self.settings.sample_rate <= 0:
            return 0.0
        samples = len(raw_audio) / bytes_per_sample
        return samples / float(self.settings.sample_rate)

    def _segment_rms_dbfs(self, raw_audio: bytes) -> float:
        if not raw_audio:
            return -120.0
        audio = np.frombuffer(raw_audio, dtype=np.int16).astype(np.float32) / 32768.0
        if audio.size == 0:
            return -120.0
        rms = float(np.sqrt(np.mean(np.square(audio))))
        if rms <= 1e-9:
            return -120.0
        return 20.0 * math.log10(rms)

    @staticmethod
    def _katakana_to_hiragana(text: str) -> str:
        result_chars: list[str] = []
        for ch in text:
            code = ord(ch)
            if 0x30A1 <= code <= 0x30F6:
                result_chars.append(chr(code - 0x60))
            else:
                result_chars.append(ch)
        return "".join(result_chars)

    def _normalize_text_for_match(self, text: str) -> str:
        normalized = unicodedata.normalize("NFKC", text).lower()
        normalized = self._katakana_to_hiragana(normalized)
        normalized = re.sub(r"[\s\u3000]+", "", normalized)
        normalized = re.sub(r"[、。,.!！?？「」『』（）()\[\]{}\"'`]", "", normalized)
        return normalized

    def _dispatch(self, text: str) -> None:
        argv = shlex.split(self.settings.dispatch_cmd)
        if not argv:
            logging.error("dispatch command is empty")
            return

        env = os.environ.copy()
        env["YATAGARASU_CWD"] = str(self.settings.workspace_path)
        started = time.monotonic()

        try:
            result = subprocess.run(
                argv,
                input=text,
                text=True,
                env=env,
                timeout=self.settings.dispatch_timeout_sec,
                capture_output=True,
                check=False,
            )
        except FileNotFoundError:
            logging.error("dispatch command not found: %s", argv[0])
            return
        except subprocess.TimeoutExpired:
            logging.error(
                "dispatch timed out after %.1fs: %s",
                self.settings.dispatch_timeout_sec,
                self.settings.dispatch_cmd,
            )
            return

        elapsed = time.monotonic() - started
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            logging.error(
                "dispatch failed rc=%s elapsed=%.2fs stderr=%s",
                result.returncode,
                elapsed,
                stderr,
            )
            return

        logging.info("dispatch succeeded elapsed=%.2fs", elapsed)

    def _play_wake_ack(self) -> bool:
        word = self.settings.wake_ack_word.strip()
        return self._play_feedback_word(word, label="wake ack")

    def _play_wake_prompt_word(self) -> bool:
        """ウェイクワード検出時の即時フィードバック（はい）を発話"""
        word = self.settings.wake_prompt_word.strip()
        return self._play_feedback_word(word, label="wake prompt")

    def _play_standby_word(self) -> bool:
        word = self.settings.standby_word.strip()
        return self._play_feedback_word(word, label="standby")

    def _play_feedback_word(self, word: str, label: str) -> bool:
        if not word:
            return True

        zunda_argv = shlex.split(self.settings.wake_ack_zunda_cmd)
        tapovoice_argv = shlex.split(self.settings.wake_ack_tapovoice_cmd)
        if not zunda_argv:
            logging.warning("%s skipped: zunda command is empty", label)
            return False
        if not tapovoice_argv:
            logging.warning("%s skipped: tapovoice command is empty", label)
            return False

        zunda_cmd = [
            *zunda_argv,
            word,
            "--stdout",
            "-s",
            self.settings.wake_ack_speaker_id,
        ]
        logging.info("%s: '%s' via `%s | %s`", label, word, " ".join(zunda_cmd), " ".join(tapovoice_argv))

        zunda_proc: subprocess.Popen[bytes] | None = None
        tapovoice_proc: subprocess.Popen[bytes] | None = None
        try:
            zunda_proc = subprocess.Popen(
                zunda_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ.copy(),
            )
            if zunda_proc.stdout is None:
                raise RuntimeError("zunda stdout pipe is not available")
            tapovoice_proc = subprocess.Popen(
                tapovoice_argv,
                stdin=zunda_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ.copy(),
            )
            zunda_proc.stdout.close()
            timeout = max(1.0, self.settings.wake_ack_timeout_sec)
            tapovoice_out, tapovoice_err = tapovoice_proc.communicate(timeout=timeout)
            zunda_out, zunda_err = zunda_proc.communicate(timeout=timeout)
            if zunda_proc.returncode != 0:
                logging.warning(
                    "%s zunda failed rc=%s stderr=%s",
                    label,
                    zunda_proc.returncode,
                    (zunda_err or b"").decode("utf-8", errors="ignore").strip(),
                )
                return False
            if tapovoice_proc.returncode != 0:
                logging.warning(
                    "%s tapovoice failed rc=%s stderr=%s",
                    label,
                    tapovoice_proc.returncode,
                    (tapovoice_err or b"").decode("utf-8", errors="ignore").strip(),
                )
                return False
            out_text = (tapovoice_out or b"").decode("utf-8", errors="ignore").strip()
            if out_text:
                logging.info("%s output: %s", label, out_text)
            return True
        except FileNotFoundError as exc:
            logging.warning("%s command not found: %s", label, exc)
            return False
        except subprocess.TimeoutExpired:
            logging.warning("%s timed out after %.1fs", label, self.settings.wake_ack_timeout_sec)
            if tapovoice_proc and tapovoice_proc.poll() is None:
                tapovoice_proc.kill()
                tapovoice_proc.wait(timeout=1)
            if zunda_proc and zunda_proc.poll() is None:
                zunda_proc.kill()
                zunda_proc.wait(timeout=1)
            return False
        except Exception as exc:
            logging.warning("%s failed: %s", label, exc)
            return False


def setup_logging(level_name: str) -> None:
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )
    # Keep listend debug readable even when root level is DEBUG.
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("huggingface_hub").setLevel(logging.INFO)


def install_signal_handlers(service: ListendService) -> None:
    def _handler(signum: int, _frame: object) -> None:
        logging.info("received signal=%s; stopping...", signum)
        service.request_stop()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def main() -> int:
    setup_logging(os.getenv("LISTEND_LOG_LEVEL", "INFO"))
    try:
        settings = ListendSettings.from_env()
    except Exception as exc:
        logging.error("failed to load settings: %s", exc)
        return 2

    setup_logging(settings.log_level)
    logging.info("workspace=%s", settings.workspace_path)
    logging.info("dispatch_cmd=%s", settings.dispatch_cmd)
    logging.info("dispatch_timeout_sec=%.1f", settings.dispatch_timeout_sec)
    logging.info("stt_backend=%s", settings.stt_backend)
    logging.info("stt_language=%s", settings.stt_language)
    if settings.stt_backend == "faster-whisper":
        logging.info("whisper_model=%s", settings.whisper_model)
        logging.info(
            "whisper_language=%s whisper_beam_size=%s",
            settings.whisper_language,
            settings.whisper_beam_size,
        )
    elif settings.stt_backend == "reazonspeech-k2":
        logging.info(
            "reazon_language=%s reazon_device=%s reazon_precision=%s",
            settings.reazon_language,
            settings.reazon_device,
            settings.reazon_precision,
        )
    logging.info("rtsp_transport=%s", settings.rtsp_transport)
    logging.info("wake_words=%s", ",".join(settings.wake_words))
    logging.info("stop_words=%s", ",".join(settings.stop_words))
    logging.info(
        "session_end_silence_sec=%.1f silence_timeout_sec=%.1f",
        settings.session_end_silence_sec,
        settings.silence_timeout_sec,
    )
    logging.info(
        "segment_end_silence_chunks=%d (chunk_ms=%d => %.0fms)",
        settings.segment_end_silence_chunks,
        settings.chunk_ms,
        settings.segment_end_silence_chunks * settings.chunk_ms,
    )
    logging.info("vad_hangover_chunks=%d", DEFAULT_VAD_HANGOVER_CHUNKS)
    logging.info("min_transcribe_rms_dbfs=%.1f", DEFAULT_MIN_TRANSCRIBE_RMS_DBFS)
    logging.info(
        "min_segment_sec=%.2f off_transcribe_cooldown_sec=%.2f",
        settings.min_segment_sec,
        settings.off_transcribe_cooldown_sec,
    )
    logging.info(
        "no_data_timeout_sec=%.1f heartbeat_sec=%.1f reconnect_delay_sec=%.1f",
        settings.no_data_timeout_sec,
        settings.heartbeat_sec,
        settings.reconnect_delay_sec,
    )
    logging.info("audio_filter=%s", DEFAULT_AUDIO_FILTER)
    logging.info("reazon_max_segment_sec=%.1f", DEFAULT_REAZON_MAX_SEGMENT_SEC)
    logging.info(
        "wake_ack=%s standby_word=%s speaker=%s timeout_sec=%.1f",
        settings.wake_ack_word if settings.wake_ack_word else "(disabled)",
        settings.standby_word if settings.standby_word else "(disabled)",
        settings.wake_ack_speaker_id,
        settings.wake_ack_timeout_sec,
    )
    logging.info("debug_detail=%s", "enabled (LISTEND_LOG_LEVEL=DEBUG)" if logging.getLogger().isEnabledFor(logging.DEBUG) else "disabled")

    try:
        service = ListendService(settings)
    except Exception as exc:
        logging.error("failed to initialize models: %s", exc)
        return 2

    install_signal_handlers(service)
    return service.run()


if __name__ == "__main__":
    sys.exit(main())
