"""镜头声明与正文引用区分，编号和时码仍按实际声明校验。"""
from __future__ import annotations

import pytest

from h3ir.validate import Context, validate


def _document(description):
    return (f"integrated_multimodal_description:\n{description}\n\n"
            "overall_soundscape:\nWind.\n\nnon_diegetic_music:\nN/A\n")


def _timeline_rules(description, **context):
    return {finding.rule for finding in validate(_document(description), Context(mode="t2va", **context))
            if finding.rule.startswith("T")}


def test_actual_chinese_t10_references_do_not_create_phantom_shots():
    description = "\n".join([
        "[Shot 1] 固定中景，积雪岩石与雪山背景。",
        "[Shot 2] At 00:03.633, 硬切到茅屋院落全身景。",
        "[Shot 3] At 00:04.300, 硬切木门正面全身景。",
        "[Shot 4] At 00:06.267, 硬切女子面部特写。",
        "[Shot 5] At 00:09.267, 硬切男子面部特写。",
        "[Shot 6] At 00:10.767, 硬切回女子特写，持续到00:12.800。保持 [Shot 4] 的同一女子、服装、发饰、机位与光线。",
        "[Shot 7] At 00:12.800, 硬切院落过肩中景。",
        "[Shot 8] At 00:14.200, 停留在 [Shot 7] 的剧情收尾：女子保持举枪姿势，男子双手已抬起，烟雾缓慢散开。",
    ])
    assert _timeline_rules(description, pinned_shots=8) == set()


@pytest.mark.parametrize("reference", [
    "Keep the same woman and lighting as in [Shot 1].",
    "保持 [Shot 1] 的同一女子、服装、机位与光线。",
    "The reflection foreshadows the doorway in [Shot 3].",
    "倒影预示 [Shot 3] 中即将出现的门。",
])
@pytest.mark.parametrize("separator", ["\n", " "])
def test_inline_references_preserve_true_shot_count_in_both_layouts(reference, separator):
    description = separator.join([
        "[Shot 1] Live-action, a woman waits beside a door.",
        f"[Shot 2] At 00:02.000, {reference}",
        "[Shot 3] At 00:04.000, the door opens.",
    ])
    assert _timeline_rules(description, pinned_shots=3) == set()


@pytest.mark.parametrize("quoted", [
    'The board displays "[Shot 7] At 00:06.000, Begin".',
    'A woman says (S1) <d>[English] [Shot 7] At 00:06.000, Begin.</d>',
])
def test_shot_marker_with_time_inside_user_words_is_not_a_declaration(quoted):
    description = f"[Shot 1] Live-action, {quoted} [Shot 2] At 00:03.000, the door opens."
    assert _timeline_rules(description, pinned_shots=2) == set()


GOOD = ("[Shot 1] Live-action, a woman waits. "
        "[Shot 2] At 00:02.000, she remembers [Shot 1] and raises a hand. "
        "[Shot 3] At 00:04.000, the door opens.")


@pytest.mark.parametrize("description,expected", [
    (GOOD.replace("[Shot 1] Live-action", "[Shot 1] At 00:00.000, Live-action"), "T2-shot1-timestamp"),
    (GOOD.replace("At 00:02.000", "At 0:2"), "T3-timestamp-format"),
    (GOOD.replace("[Shot 2] At 00:02.000,", "[Shot 2]"), "T4-missing-cut-time"),
    (GOOD.replace("[Shot 2] At 00:02.000,", "[Shot 2] 在 00:02.000，"), "T4-missing-cut-time"),
    (GOOD.replace("At 00:04.000", "At 00:01.000"), "T5-non-increasing"),
    (GOOD.replace("At 00:04.000", "At 00:09.000"), "T6-time-past-end"),
    (GOOD.replace("[Shot 2] At", "[Shot 4] At"), "T8-shot-numbering"),
])
def test_actual_declarations_still_enforce_numbering_and_timestamps(description, expected):
    assert expected in _timeline_rules(description, duration_s=8)


def test_missing_time_after_scenetrans_is_still_a_declaration():
    description = "[Shot 1] Live-action, a woman waits. [Shot 2] <scenetrans> the door opens."
    assert "T4-missing-cut-time" in _timeline_rules(description)
