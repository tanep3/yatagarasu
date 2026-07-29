#!/usr/bin/env python3
"""SBERT based intent router for Yatagarasu.

The router is intentionally split into definitions, scoring, and decisions.
Callers decide how to execute returned flags; this module only describes what
the utterance appears to request.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Protocol

import numpy as np


DEFAULT_MODEL = "cl-nagoya/ruri-v3-70m"
DEFAULT_HIGH_THRESHOLD = 0.78
DEFAULT_MIDDLE_THRESHOLD = 0.68
DEFAULT_TOP_K = 5
ROUTER_VERSION = "1"

ACTION_ORDER = (
    "move_camera_calibrate",
    "move_camera_left",
    "move_camera_right",
    "move_camera_up",
    "move_camera_down",
    "capture_image",
    "recall_memory",
)

COMPOSITE_VIEW_INTENTS = frozenset(
    {
        "view_document_summarize_translate",
        "view_document_transcribe_translate",
    }
)


@dataclass(frozen=True)
class RouterSettings:
    enabled: bool
    dry_run: bool
    model_name: str
    device: str
    offline: bool
    high_threshold: float
    middle_threshold: float
    top_k: int

    @classmethod
    def from_env(cls) -> "RouterSettings":
        return cls(
            enabled=env_bool("YATAGARASU_SBERT_ROUTER_ENABLED", False),
            dry_run=env_bool("YATAGARASU_SBERT_DRY_RUN", True),
            model_name=os.getenv("YATAGARASU_SBERT_MODEL", DEFAULT_MODEL).strip()
            or DEFAULT_MODEL,
            device=os.getenv("YATAGARASU_SBERT_DEVICE", "cpu").strip() or "cpu",
            offline=env_bool("YATAGARASU_SBERT_OFFLINE", False)
            or env_bool("HF_HUB_OFFLINE", False)
            or env_bool("TRANSFORMERS_OFFLINE", False),
            high_threshold=env_float(
                "YATAGARASU_SBERT_HIGH_THRESHOLD", DEFAULT_HIGH_THRESHOLD
            ),
            middle_threshold=env_float(
                "YATAGARASU_SBERT_MIDDLE_THRESHOLD", DEFAULT_MIDDLE_THRESHOLD
            ),
            top_k=max(1, env_int("YATAGARASU_SBERT_TOP_K", DEFAULT_TOP_K)),
        )


@dataclass(frozen=True)
class IntentDefinition:
    intent_id: str
    category: str
    skill: str
    action: str
    templates: tuple[str, ...]
    threshold: float
    allow_multi_hit: bool
    requires_llm: bool
    priority: int
    llm_instruction: str
    gate_terms: tuple[str, ...] = ()
    gate_required_groups: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class IntentHit:
    intent_id: str
    category: str
    score: float
    level: str
    order_index: int
    matched_template: str
    requires_llm: bool
    llm_instruction: str


@dataclass(frozen=True)
class RouterDecision:
    enabled: bool
    dry_run: bool
    original_text: str
    high_hits: tuple[IntentHit, ...]
    middle_hits: tuple[IntentHit, ...]
    top_hits: tuple[IntentHit, ...]
    flags: tuple[str, ...]
    requires_llm: bool
    llm_instructions: tuple[str, ...]

    @property
    def has_router_hit(self) -> bool:
        return bool(self.high_hits or self.middle_hits)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "original_text": self.original_text,
            "high_hits": [asdict(hit) for hit in self.high_hits],
            "middle_hits": [asdict(hit) for hit in self.middle_hits],
            "top_hits": [asdict(hit) for hit in self.top_hits],
            "flags": list(self.flags),
            "requires_llm": self.requires_llm,
            "llm_instructions": list(self.llm_instructions),
        }


@dataclass(frozen=True)
class TemplateEntry:
    intent: IntentDefinition
    template: str


class Embedder(Protocol):
    def encode(self, texts: Iterable[str]) -> np.ndarray:
        ...


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str, device: str, offline: bool) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "sentence-transformers is required for SBERT Router. "
                "Install CPU dependencies first."
            ) from exc

        logging.info("loading SBERT model: %s device=%s", model_name, device)
        self._model = SentenceTransformer(
            model_name,
            device=device,
            local_files_only=offline,
        )

    def encode(self, texts: Iterable[str]) -> np.ndarray:
        values = list(texts)
        if not values:
            return np.empty((0, 0), dtype=np.float32)
        embeddings = self._model.encode(
            values,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(embeddings, dtype=np.float32)


class IntentRouter:
    def __init__(
        self,
        settings: RouterSettings,
        intents: tuple[IntentDefinition, ...],
        embedder: Embedder,
    ) -> None:
        self.settings = settings
        self.intents = intents
        self.embedder = embedder
        self.entries = tuple(
            TemplateEntry(intent=intent, template=template)
            for intent in intents
            for template in intent.templates
        )
        self._template_embeddings = self.embedder.encode(
            entry.template for entry in self.entries
        )
        logging.info(
            "SBERT Router ready: intents=%d templates=%d model=%s dry_run=%s",
            len(self.intents),
            len(self.entries),
            self.settings.model_name,
            self.settings.dry_run,
        )

    @classmethod
    def from_env(cls) -> "IntentRouter | None":
        settings = RouterSettings.from_env()
        if not settings.enabled:
            logging.info("SBERT Router disabled")
            return None
        intents = build_intents_from_env(settings)
        if not intents:
            logging.warning("SBERT Router enabled but no intent templates are configured")
            return None
        embedder = SentenceTransformerEmbedder(
            settings.model_name,
            settings.device,
            settings.offline,
        )
        return cls(settings=settings, intents=intents, embedder=embedder)

    def route(self, text: str) -> RouterDecision:
        original_text = " ".join(text.split()).strip()
        if not original_text:
            return empty_decision(self.settings, original_text)
        if len(self.entries) == 0:
            return empty_decision(self.settings, original_text)

        query_embedding = self.embedder.encode([original_text])
        if query_embedding.size == 0:
            return empty_decision(self.settings, original_text)

        scores = np.matmul(self._template_embeddings, query_embedding[0])
        best_by_intent = self._best_hits_by_intent(scores, original_text)
        raw_high_hits = tuple(
            hit for hit in best_by_intent if hit.score >= self._threshold_for(hit.intent_id)
        )
        high_hits = select_high_hits(raw_high_hits)
        middle_hits = tuple(
            hit
            for hit in best_by_intent
            if self.settings.middle_threshold <= hit.score < self._threshold_for(hit.intent_id)
        )
        top_hits = tuple(
            sorted(best_by_intent, key=lambda hit: hit.score, reverse=True)[
                : self.settings.top_k
            ]
        )
        flags = flags_from_hits(high_hits)
        llm_instructions = tuple(
            hit.llm_instruction for hit in high_hits if hit.requires_llm and hit.llm_instruction
        )
        requires_llm = bool(llm_instructions or middle_hits)
        return RouterDecision(
            enabled=True,
            dry_run=self.settings.dry_run,
            original_text=original_text,
            high_hits=high_hits,
            middle_hits=middle_hits,
            top_hits=top_hits,
            flags=flags,
            requires_llm=requires_llm,
            llm_instructions=llm_instructions,
        )

    def _threshold_for(self, intent_id: str) -> float:
        for intent in self.intents:
            if intent.intent_id == intent_id:
                return intent.threshold
        return self.settings.high_threshold

    def _best_hits_by_intent(
        self, scores: np.ndarray, original_text: str
    ) -> tuple[IntentHit, ...]:
        gated_text = normalize_for_gate(original_text)
        best: dict[str, tuple[TemplateEntry, float]] = {}
        for entry, score_value in zip(self.entries, scores):
            if not gate_matches(
                gated_text,
                entry.intent.gate_terms,
                entry.intent.gate_required_groups,
            ):
                continue
            score = float(score_value)
            current = best.get(entry.intent.intent_id)
            if current is None or score > current[1]:
                best[entry.intent.intent_id] = (entry, score)

        hits = [
            IntentHit(
                intent_id=entry.intent.intent_id,
                category=entry.intent.category,
                score=round(score, 6),
                level=level_for_score(
                    score,
                    threshold=entry.intent.threshold,
                    middle_threshold=self.settings.middle_threshold,
                ),
                order_index=order_index_for_intent(gated_text, entry.intent),
                matched_template=entry.template,
                requires_llm=entry.intent.requires_llm,
                llm_instruction=entry.intent.llm_instruction,
            )
            for entry, score in best.values()
            if score >= self.settings.middle_threshold
        ]
        return tuple(sorted(hits, key=lambda hit: (-hit.score, hit.intent_id)))


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        logging.warning("Invalid float env %s=%s; fallback=%s", name, value, default)
        return default


def env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        logging.warning("Invalid int env %s=%s; fallback=%s", name, value, default)
        return default


def split_templates(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split("|") if part.strip())


def templates(env_name: str, default: str) -> tuple[str, ...]:
    return split_templates(os.getenv(env_name, default))


def intent(
    settings: RouterSettings,
    intent_id: str,
    category: str,
    skill: str,
    action: str,
    env_name: str,
    default_templates: str,
    requires_llm: bool,
    priority: int,
    llm_instruction: str = "",
    threshold: float | None = None,
    allow_multi_hit: bool = True,
    gate_terms: tuple[str, ...] = (),
    gate_required_groups: tuple[tuple[str, ...], ...] = (),
) -> IntentDefinition:
    return IntentDefinition(
        intent_id=intent_id,
        category=category,
        skill=skill,
        action=action,
        templates=templates(env_name, default_templates),
        threshold=settings.high_threshold if threshold is None else threshold,
        allow_multi_hit=allow_multi_hit,
        requires_llm=requires_llm,
        priority=priority,
        llm_instruction=llm_instruction,
        gate_terms=gate_terms,
        gate_required_groups=gate_required_groups,
    )


def build_intents_from_env(settings: RouterSettings) -> tuple[IntentDefinition, ...]:
    definitions = (
        intent(
            settings,
            "move_camera_left",
            "move",
            "move-camera",
            "move_camera_left",
            "YATAGARASU_INTENT_MOVE_LEFT",
            "左を向いて|左を見て|左に向けて|カメラを左|左側を見て",
            False,
            20,
            gate_terms=("左",),
        ),
        intent(
            settings,
            "move_camera_right",
            "move",
            "move-camera",
            "move_camera_right",
            "YATAGARASU_INTENT_MOVE_RIGHT",
            "右を向いて|右を見て|右に向けて|カメラを右|右側を見て",
            False,
            20,
            gate_terms=("右",),
        ),
        intent(
            settings,
            "move_camera_up",
            "move",
            "move-camera",
            "move_camera_up",
            "YATAGARASU_INTENT_MOVE_UP",
            "上を向いて|上を見て|上に向けて|カメラを上|上側を見て",
            False,
            30,
            gate_terms=("上",),
        ),
        intent(
            settings,
            "move_camera_down",
            "move",
            "move-camera",
            "move_camera_down",
            "YATAGARASU_INTENT_MOVE_DOWN",
            "下を向いて|下を見て|下に向けて|カメラを下|下側を見て",
            False,
            30,
            gate_terms=("下",),
        ),
        intent(
            settings,
            "move_camera_calibrate",
            "move",
            "move-camera",
            "move_camera_calibrate",
            "YATAGARASU_INTENT_MOVE_CALIBRATE",
            "キャリブレーションして|カメラを初期化して|カメラの位置を直して|位置合わせして",
            False,
            10,
            threshold=max(settings.high_threshold, 0.82),
            gate_terms=("キャリブレーション", "初期化", "位置合わせ", "位置を直"),
        ),
        intent(
            settings,
            "view_scene",
            "view",
            "view",
            "capture_image",
            "YATAGARASU_INTENT_VIEW_SCENE",
            "今何が見える|何が見える|見えているものを説明して|周りを見て|状況を教えて",
            True,
            40,
            "撮影画像を見て、画像全体の状況と見えているものを短く説明してください。",
        ),
        intent(
            settings,
            "view_face",
            "view",
            "view",
            "capture_image",
            "YATAGARASU_INTENT_VIEW_FACE",
            "僕の顔を見て|顔を見て|表情を見て|こっちを見て|私の顔を確認して",
            True,
            40,
            "撮影画像を見て、顔や表情から読み取れる範囲を中心に説明してください。",
            gate_terms=("顔", "表情", "こっち"),
        ),
        intent(
            settings,
            "view_object",
            "view",
            "view",
            "capture_image",
            "YATAGARASU_INTENT_VIEW_OBJECT",
            "これを見て|これ何|この物を見て|手元を見て|見せているものを確認して",
            True,
            40,
            "撮影画像を見て、ユーザーがカメラに見せている物体を中心に説明してください。",
            gate_terms=("これ", "物", "手元", "見せ"),
        ),
        intent(
            settings,
            "view_document_read",
            "view",
            "view",
            "capture_image",
            "YATAGARASU_INTENT_VIEW_DOCUMENT_READ",
            "この書類を読んで|何が書いてある|文章を読んで|内容を教えて|これ読める",
            True,
            40,
            "画像内の文字を読み取り、何が書かれているかを自然に説明してください。",
            gate_terms=("書類", "書いて", "文章", "読ん", "内容"),
        ),
        intent(
            settings,
            "view_document_summarize",
            "view",
            "view",
            "capture_image",
            "YATAGARASU_INTENT_VIEW_DOCUMENT_SUMMARIZE",
            "この書類を要約して|内容を要約して|ざっくりまとめて|要点を教えて|ポイントをまとめて",
            True,
            40,
            "画像内の文字を読み取り、重要な要点だけを短く要約してください。",
            gate_terms=("書類", "要約", "まとめ", "要点", "ポイント"),
        ),
        intent(
            settings,
            "view_document_translate",
            "view",
            "view",
            "capture_image",
            "YATAGARASU_INTENT_VIEW_DOCUMENT_TRANSLATE",
            "この画像を翻訳して|これを和訳して|日本語に訳して|翻訳して|英語を訳して|この文章を訳して",
            True,
            40,
            "画像内の文字を読み取り、日本語訳だけを返してください。原文の転記や英文の読み上げは不要です。",
            gate_terms=("画像", "和訳", "訳", "翻訳", "英語"),
        ),
        intent(
            settings,
            "view_document_transcribe",
            "view",
            "view",
            "capture_image",
            "YATAGARASU_INTENT_VIEW_DOCUMENT_TRANSCRIBE",
            "文字起こしして|書いてある文字をそのまま読んで|全文を読んで|テキストにして|OCRして",
            True,
            40,
            "画像内の文字を読み取れる範囲でできるだけ原文のまま転記してください。",
            gate_terms=("文字起こし", "全文", "テキスト", "ocr", "そのまま"),
        ),
        intent(
            settings,
            "view_document_summarize_translate",
            "view",
            "view",
            "capture_image",
            "YATAGARASU_INTENT_VIEW_DOCUMENT_SUMMARIZE_TRANSLATE",
            "この書類を要約して和訳して|要約して日本語に訳して|翻訳して要約して|和訳して要点を教えて",
            True,
            39,
            "画像内の文章を読み取り、日本語へ翻訳したうえで要点を短くまとめてください。",
            gate_required_groups=(
                ("要約", "まとめ", "要点"),
                ("和訳", "訳", "翻訳"),
            ),
        ),
        intent(
            settings,
            "view_document_transcribe_translate",
            "view",
            "view",
            "capture_image",
            "YATAGARASU_INTENT_VIEW_DOCUMENT_TRANSCRIBE_TRANSLATE",
            "文字起こしして和訳して|全文を読んで日本語に訳して|原文を書いて訳して",
            True,
            39,
            "画像内の文章を原文に近く転記し、その後に日本語訳を付けてください。",
            gate_required_groups=(
                ("文字起こし", "全文", "原文"),
                ("和訳", "訳", "翻訳"),
            ),
        ),
        intent(
            settings,
            "recall_summarize",
            "recall",
            "recall",
            "recall_memory",
            "YATAGARASU_INTENT_RECALL_SUMMARIZE",
            "覚えてる|前に話したことをまとめて|記憶を要約して|思い出して説明して|前の話を整理して",
            True,
            50,
            "関連する記憶候補を整理し、ユーザーが思い出せるように短く要約してください。",
            gate_terms=("覚え", "記憶", "思い出", "前"),
        ),
        intent(
            settings,
            "recall_confirm",
            "recall",
            "recall",
            "recall_memory",
            "YATAGARASU_INTENT_RECALL_CONFIRM",
            "前に言ったっけ|覚えてるか確認して|記憶にあるか見て|前に話したことある|聞いたことある",
            True,
            50,
            "関連する記憶があるかどうかをまず答えてください。",
            gate_terms=("覚え", "記憶", "前", "聞いた"),
        ),
        intent(
            settings,
            "recall_topic",
            "recall",
            "recall",
            "recall_memory",
            "YATAGARASU_INTENT_RECALL_TOPIC",
            "について覚えてる|について思い出して|の記憶ある|について前に言った|について話したことある",
            True,
            50,
            "ユーザーが指定したトピックに関係する記憶だけを使い、要点を短くまとめてください。",
            gate_terms=("覚え", "記憶", "思い出", "前", "話した"),
        ),
        intent(
            settings,
            "recall_compare",
            "recall",
            "recall",
            "recall_memory",
            "YATAGARASU_INTENT_RECALL_COMPARE",
            "前と比べて|前回と違う|前に話した内容と比較して|記憶と照らして|前の情報と比べて",
            True,
            50,
            "記憶候補と現在の入力または観測結果を比較して答えてください。",
            gate_terms=("前", "前回", "比べ", "比較", "記憶"),
        ),
        intent(
            settings,
            "recall_contextualize",
            "recall",
            "recall",
            "recall_memory",
            "YATAGARASU_INTENT_RECALL_CONTEXTUALIZE",
            "前に話したことを踏まえて|覚えていることを参考に|記憶をもとに考えて|過去の話から判断して",
            True,
            50,
            "記憶候補を背景情報として使い、現在の質問に自然に答えてください。",
            gate_terms=("前", "覚え", "記憶", "過去", "踏まえて"),
        ),
    )
    return tuple(intent for intent in definitions if intent.templates)


def level_for_score(score: float, threshold: float, middle_threshold: float) -> str:
    if score >= threshold:
        return "high"
    if score >= middle_threshold:
        return "middle"
    return "low"


def katakana_to_hiragana(text: str) -> str:
    chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if 0x30A1 <= code <= 0x30F6:
            chars.append(chr(code - 0x60))
        else:
            chars.append(ch)
    return "".join(chars)


def normalize_for_gate(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).lower()
    normalized = katakana_to_hiragana(normalized)
    return re.sub(r"[\s\u3000、。,.!！?？「」『』（）()\[\]{}\"'`]", "", normalized)


def gate_matches(
    normalized_text: str,
    gate_terms: tuple[str, ...],
    gate_required_groups: tuple[tuple[str, ...], ...] = (),
) -> bool:
    if gate_terms and not any(
        normalize_for_gate(term) in normalized_text for term in gate_terms
    ):
        return False
    return all(
        any(normalize_for_gate(term) in normalized_text for term in group)
        for group in gate_required_groups
    )


def order_index_for_intent(normalized_text: str, intent: IntentDefinition) -> int:
    terms = intent.gate_terms
    if intent.gate_required_groups:
        terms = tuple(term for group in intent.gate_required_groups for term in group)
    positions = [
        normalized_text.find(normalize_for_gate(term))
        for term in terms
        if normalize_for_gate(term) in normalized_text
    ]
    if not positions:
        return 10**9
    return min(positions)


def flags_from_hits(hits: Iterable[IntentHit]) -> tuple[str, ...]:
    move_flags: list[str] = []
    has_view = False
    has_recall = False
    for hit in hits:
        if hit.category == "move":
            if hit.intent_id not in move_flags:
                move_flags.append(hit.intent_id)
        elif hit.category == "view":
            has_view = True
        elif hit.category == "recall":
            has_recall = True

    flags = list(move_flags)
    if has_view:
        flags.append("capture_image")
    if has_recall:
        flags.append("recall_memory")
    return tuple(flags)


def select_high_hits(hits: Iterable[IntentHit]) -> tuple[IntentHit, ...]:
    by_category: dict[str, list[IntentHit]] = {}
    for hit in hits:
        by_category.setdefault(hit.category, []).append(hit)

    selected: list[IntentHit] = []
    selected.extend(
        sorted(by_category.get("move", ()), key=lambda hit: (hit.order_index, hit.intent_id))
    )

    view_hits = by_category.get("view", [])
    if view_hits:
        composite = [hit for hit in view_hits if hit.intent_id in COMPOSITE_VIEW_INTENTS]
        selected.append(max(composite or view_hits, key=lambda hit: hit.score))

    recall_hits = by_category.get("recall", [])
    if recall_hits:
        selected.append(max(recall_hits, key=lambda hit: hit.score))

    known = {"move", "view", "recall"}
    for category, category_hits in by_category.items():
        if category not in known:
            selected.extend(category_hits)

    return tuple(
        sorted(
            selected,
            key=lambda hit: (hit.order_index, category_order(hit.category), -hit.score),
        )
    )


def category_order(category: str) -> int:
    order = {"move": 10, "view": 20, "recall": 30}
    return order.get(category, 99)


def empty_decision(settings: RouterSettings, original_text: str) -> RouterDecision:
    return RouterDecision(
        enabled=settings.enabled,
        dry_run=settings.dry_run,
        original_text=original_text,
        high_hits=(),
        middle_hits=(),
        top_hits=(),
        flags=(),
        requires_llm=False,
        llm_instructions=(),
    )


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def resolve_workspace_path() -> Path:
    raw = os.getenv("YATAGARASU_CWD", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.cwd().resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description="Yatagarasu SBERT Intent Router")
    parser.add_argument("text", nargs="?", default="", help="text to route")
    parser.add_argument("--json", action="store_true", help="emit JSON (default)")
    parser.add_argument("--top-k", type=int, default=None, help="top candidate count")
    parser.add_argument("--no-model", action="store_true", help="do not load SBERT model")
    parser.add_argument("--list-intents", action="store_true", help="list intent definitions")
    args = parser.parse_args()

    workspace = resolve_workspace_path()
    load_env_file(workspace / ".env")
    settings = RouterSettings.from_env()
    if args.top_k is not None:
        settings = RouterSettings(
            enabled=settings.enabled,
            dry_run=settings.dry_run,
            model_name=settings.model_name,
            device=settings.device,
            offline=settings.offline,
            high_threshold=settings.high_threshold,
            middle_threshold=settings.middle_threshold,
            top_k=max(1, args.top_k),
        )
    intents = build_intents_from_env(settings)

    if args.list_intents or args.no_model:
        print(
            json.dumps(
                {
                    "settings": asdict(settings),
                    "intent_count": len(intents),
                    "template_count": sum(len(intent.templates) for intent in intents),
                    "intents": [asdict(intent) for intent in intents],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not args.text:
        parser.error("text is required unless --list-intents or --no-model is used")

    router = IntentRouter(
        settings=settings,
        intents=intents,
        embedder=SentenceTransformerEmbedder(
            settings.model_name,
            settings.device,
            settings.offline,
        ),
    )
    decision = router.route(args.text)
    print(json.dumps(decision.to_json_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
