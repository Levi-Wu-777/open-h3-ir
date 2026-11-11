"""实际写作消息保留姿态观察，不加入作者的姿态禁令。"""
from __future__ import annotations

import json
from types import SimpleNamespace

from h3ir.draft import deterministic_draft
from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode, Role
from h3ir.prose import compose_brief


class CapturingBackend:
    def chat(self, messages, **kwargs):
        self.messages = messages
        return SimpleNamespace(content="unused")


def test_compose_passes_observed_pose_without_forbidding_its_use():
    asset = AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256="pose-plate")
    card = AssetCard(
        sha256=asset.sha256,
        kind=AssetKind.IMAGE,
        subjects=[{
            "kind": "person",
            "descriptor": "the seated woman",
            "attributes": ["red jacket"],
            "pose": ["seated with crossed legs"],
        }],
    )
    brief = Brief(intent="Keep the woman's seated pose.", assets=[asset])
    cards = {asset.sha256: card}
    plan = deterministic_draft(brief, Mode.REF2VA, cards)
    backend = CapturingBackend()

    compose_brief(
        backend, brief, plan.subjects, cards, plan.target,
        tuple(entry.label for entry in plan.manifest),
        mode=Mode.REF2VA, manifest=plan.manifest,
    )

    content = backend.messages[-1]["content"]
    ask = content if isinstance(content, str) else content[0]["text"]
    facts = json.loads(ask.split("\n\n", 1)[1])
    assert facts["request"] == brief.intent
    assert facts["asset_cards"][0]["subjects"][0]["pose"] == ["seated with crossed legs"]
    assert all("pose does NOT carry over" not in line for line in facts["subjects"])
