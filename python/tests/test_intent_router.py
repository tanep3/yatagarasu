from __future__ import annotations

import numpy as np

from intent_router import (
    IntentRouter,
    RouterSettings,
    build_intents_from_env,
    flags_from_hits,
)


class KeywordEmbedder:
    features = (
        "右",
        "左",
        "上",
        "下",
        "__view__",
        "覚えて",
        "書類",
        "要約",
        "和訳",
    )

    def encode(self, texts):
        rows = []
        for text in texts:
            row = np.array(
                [
                    1.0
                    if ("見え" in text if feature == "__view__" else feature in text)
                    else 0.0
                    for feature in self.features
                ]
            )
            norm = np.linalg.norm(row)
            if norm > 0:
                row = row / norm
            rows.append(row)
        return np.asarray(rows, dtype=np.float32)


def settings() -> RouterSettings:
    return RouterSettings(
        enabled=True,
        dry_run=True,
        model_name="fake",
        device="cpu",
        offline=True,
        high_threshold=0.5,
        middle_threshold=0.4,
        top_k=5,
    )


def router() -> IntentRouter:
    s = settings()
    return IntentRouter(s, build_intents_from_env(s), KeywordEmbedder())


def test_move_right_only_does_not_require_llm():
    decision = router().route("右を向いて")

    assert "move_camera_right" in decision.flags
    assert "capture_image" not in decision.flags
    assert decision.requires_llm is False


def test_move_and_view_requires_llm_with_deduped_capture():
    decision = router().route("右を向いて何が見える")

    assert "move_camera_right" in decision.flags
    assert "move_camera_left" not in decision.flags
    assert "move_camera_up" not in decision.flags
    assert "move_camera_down" not in decision.flags
    assert decision.flags.count("capture_image") == 1
    assert decision.requires_llm is True


def test_colloquial_view_scene_conjugations_trigger_capture():
    for text in ("今何が見えてる", "今何が見えている", "何が見えますか"):
        decision = router().route(text)

        assert decision.flags == ("capture_image",)
        assert decision.requires_llm is True
        assert decision.high_hits[0].intent_id == "view_scene"


def test_move_sequence_keeps_opposite_directions():
    decision = router().route("右を向いて左を向いて")

    assert decision.flags == ("move_camera_right", "move_camera_left")
    assert decision.requires_llm is False


def test_flags_from_hits_keeps_move_sequence_and_dedupes_view():
    decision = router().route("右を向いて上を向いて何が見える")

    assert decision.flags.index("move_camera_right") < decision.flags.index("move_camera_up")
    assert decision.flags.count("capture_image") == 1
    assert flags_from_hits(decision.high_hits) == decision.flags


def test_document_summary_translation_prefers_composite_intent():
    decision = router().route("この書類を要約して和訳して")
    high_ids = {hit.intent_id for hit in decision.high_hits}

    assert "view_document_summarize_translate" in high_ids
    assert "view_document_summarize" not in high_ids
    assert "view_document_translate" not in high_ids
    assert decision.flags == ("capture_image",)
    assert decision.requires_llm is True
