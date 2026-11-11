"""镜头转场与运镜可使用自由描述；不再执行作者的闭集词表策略。"""
from __future__ import annotations

from pathlib import Path

import pytest

from h3ir.validate import Context, validate

GOLDEN = Path(__file__).resolve().parents[1] / "h3ir/golden"


def _doc(desc: str) -> str:
    return (f"integrated_multimodal_description: {desc}\n\n"
            "overall_soundscape: Rain runs off the awning.\n\n"
            "non_diegetic_music: N/A\n")


def _ctx() -> Context:
    return Context(mode="t2va", n_pictures=0, duration_s=294 / 24)


SHOT1 = ("[Shot 1] Live-action, cinematic, the fishmonger sets a crate on the stall. The camera "
         "pushes in with small amplitude at slow speed.")


@pytest.mark.parametrize("opening", [
    "the camera tracks alongside the crowd with small amplitude at slow speed",
    "the framing changes and the crowd fills the frame",
    "the scene cuts to a wide of the market",
    "the whip-pan resolves sharply onto the stall",
    "the camera cuts to a wide of the market",
    "the shot cuts to the empty stall",
    "the shot transitions to the empty stall",
    "the shot changes to the empty stall",
    "the shot switches to the empty stall",
    "a cross-dissolve carries the frame into the empty stall",
    "the shot fades to the empty stall",
    "a slow wipe reveals the empty stall",
])
def test_freely_described_transitions_are_valid(opening):
    text = _doc(f"{SHOT1} [Shot 2] At 00:06.000, {opening}.")
    assert validate(text, _ctx()) == []


@pytest.mark.parametrize("camera", [
    "The camera pushes in with small amplitude at normal speed.",
    "The camera pushes in with moderate amplitude at slow speed.",
    "The camera tracks alongside the car at a low angle, moving at high speed.",
    "The camera pans right with small amplitude at slow speed.",
    "The camera pans right with large amplitude at fast speed.",
    "The camera pushes in toward the crate of ice.",
    "镜头沿着水面缓慢滑行，随后飞向树梢。",
    "",
])
def test_camera_wording_is_not_limited_to_a_closed_vocabulary(camera):
    text = _doc(f"[Shot 1] Live-action, cinematic, the vendor turns. {camera}")
    assert validate(text, _ctx()) == []


@pytest.mark.parametrize("name,ctx", [
    ("official_fl2va_example.txt", Context(mode="fl2va", n_pictures=2, duration_s=8.0)),
    ("shipped_repeated_shot.txt", Context(n_pictures=2, duration_s=8.0)),
    ("official_ref2va_example.txt", Context(n_pictures=4, n_videos=2, n_audios=1)),
    ("t2va.ir.txt", Context(mode="t2va", n_pictures=0, duration_s=10.125)),
])
def test_existing_artifacts_remain_valid_after_removing_author_vocabulary_gates(name, ctx):
    found = validate((GOLDEN / name).read_text(encoding="utf-8"), ctx)
    assert not [f for f in found if f.severity == "ERROR"], found
    assert not {f.rule for f in found} & {"P7-cut-phrase-off-vocabulary", "P8-camera-modifier-off-vocabulary"}
