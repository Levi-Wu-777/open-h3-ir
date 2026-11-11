"""平台泛音频参考只陈述已给事实，不预设配乐或音轨复制。"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from h3ir.analyse import analyse_audio
from h3ir.contract import ROLES_BY_KIND
from h3ir.draft import deterministic_draft
from h3ir.models import AssetKind, AssetRef, Brief, Mode, Role
from h3ir.plan import audio_relations
from h3ir.prose import compose_brief
from h3ir.render import render_ir


class CapturingBackend:
    def chat(self, messages, **kwargs):
        self.messages = messages
        return SimpleNamespace(content="model text")


@pytest.mark.parametrize("note", ["a Japanese spoken voice", "rain and footsteps", "quiet piano music"])
def test_generic_audio_stays_neutral_in_actual_card_plan_render_and_model_message(note):
    reference = AssetRef(
        kind=AssetKind.AUDIO, role=Role.AUDIO_REFERENCE, sha256="audio",
        note=note, role_stated=True,
    )
    card = analyse_audio(reference)
    assert card.summary == f"an audio reference, described by the caller as: {note}."
    assert card.timbre == card.music == ""
    brief = Brief(intent="Use this audio as a reference.", assets=[reference])
    cards = {reference.sha256: card}
    plan = deterministic_draft(brief, Mode.REF2VA, cards)
    assert plan.task_types == ["audio reference"]
    assert audio_relations(plan) == [
        ("<Audio 1>", "reference", "<Audio 1> is referenced according to the caller's request")
    ]
    text = render_ir(plan).prompt
    assert "<Audio 1> is an audio reference for the target video" in text
    assert "<Audio 1>: reference -" in text
    assert "background music" not in text
    assert "partially_copy" not in text and "fully_copy" not in text
    assert "reused" not in text

    backend = CapturingBackend()
    compose_brief(
        backend, brief, plan.subjects, cards, plan.target,
        tuple(entry.label for entry in plan.manifest), mode=Mode.REF2VA,
        manifest=plan.manifest,
    )
    content = backend.messages[-1]["content"]
    ask = content if isinstance(content, str) else content[0]["text"]
    facts = json.loads(ask.split("\n\n", 1)[1])
    assert facts["manifest"][0]["role"] == "audio_reference"
    assert facts["asset_cards"][0]["summary"] == card.summary
    assert facts["request"] == brief.intent
    assert Role.AUDIO_REFERENCE in ROLES_BY_KIND["audio"]
