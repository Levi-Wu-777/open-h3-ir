"""官方格式与用户约束保留，作者偏好不再拦截或改写真实内容。"""
from __future__ import annotations

import ast
from pathlib import Path
import re

import pytest

from h3ir.grid import Target
from h3ir.models import Brief, Finding, Mode
from h3ir.creativity import Creativity, build
from h3ir.policies import (DISABLED_AUTHOR_RULES, ENGINEERING_RULES, OFFICIAL_RULES,
                           USER_RULES, active_findings, enabled, origin)
from h3ir.repair import repair
from h3ir.shots import shot_schema, validate_proposal
from h3ir.validate import Context, validate

BASE = ("integrated_multimodal_description:\n[Shot 1] Live-action, a child opens a door.\n\n"
        "overall_soundscape:\nA latch clicks.\n\nnon_diegetic_music:\nN/A\n")
REF = ("subject_definitions:\n<Subject 1>: the child from <Picture 1>, wearing a red coat.\n\n"
       "summary:\n[reference generation] <Subject 1> opens a door.\n\n"
       "retention_analysis:\n<Subject 1>: fully_preserved - the red coat remains.\n\n"
       "detailed_description:\nThe target video is in live-action style.\n"
       "[Shot 1] <Subject 1> opens a door.\n\n"
       "overall_soundscape:\nA latch clicks.\n\nnon_diegetic_music:\nN/A\n")


def test_every_emittable_rule_is_explicitly_classified():
    root = Path(__file__).resolve().parents[1] / "h3ir"
    emitted = set()
    for path in root.rglob("*.py"):
        if path.name == "policies.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                if re.fullmatch(r"[A-Z]\d+[a-z]?-[a-z][a-z0-9-]*", node.value):
                    emitted.add(node.value)
    groups = [set(OFFICIAL_RULES), set(USER_RULES), set(ENGINEERING_RULES), set(DISABLED_AUTHOR_RULES)]
    assert emitted, "the scan must see actual rule IDs"
    classified = set().union(*groups)
    assert emitted <= classified, sorted(emitted - classified)
    assert sum(map(len, groups)) == len(classified), "a rule must have exactly one origin"
    assert all(re.fullmatch(r"[A-Z]\d+[a-z]?-[a-z][a-z0-9-]*", rule) for rule in classified)


@pytest.mark.parametrize("rule", sorted(DISABLED_AUTHOR_RULES))
def test_disabled_author_findings_cannot_reach_the_caller(rule):
    assert origin(rule) == "author"
    assert not enabled(rule)
    assert active_findings([Finding(rule, "ERROR", "former author policy")]) == []


@pytest.mark.parametrize("body", [
    'Live-action, a dashboard displays "现在出发" and "Ready".',
    "Live-action, the child’s red coat catches moonlight—then disappears into fog.",
    "Live-action, a child opens a door.",
    "Live-action, " + "a cloud changes shape. " * 750,
    "Live-action, I describe a field while <think> is written on a board.",
])
def test_content_is_not_rejected_for_text_camera_unicode_or_length(body):
    text = BASE.replace("Live-action, a child opens a door.", body)
    assert validate(text, Context(mode="t2va", duration_s=8)) == []


@pytest.mark.parametrize("level", list(Creativity))
def test_creativity_preference_does_not_gate_supplied_content(level):
    text = BASE.replace("a child opens a door.", 'a child reads "欢迎" on the door.')
    findings = validate(text, Context(mode="t2va", duration_s=8, scope=build("a child opens a door", level=level)))
    assert not any(f.rule.startswith("Q") for f in findings)


def test_submillisecond_policy_floor_and_repeated_shots_do_not_reject():
    text = BASE.replace("opens a door.", "opens a door. [Shot 2] At 00:00.001, a child opens a door.")
    assert validate(text, Context(mode="t2va", duration_s=8)) == []


def test_subject_definition_need_not_use_the_english_word_is():
    assert validate(REF, Context(n_pictures=1, duration_s=8)) == []


@pytest.mark.parametrize("text,expected", [
    (REF.replace("fully_preserved", "invented_marker"), "R2-illegal-marker"),
    (REF.replace("<Picture 1>", "<Picture 9>"), "L3-phantom-media"),
    (REF.replace("[Shot 1] <Subject 1>", "[Shot 1] <Subject 9>"), "L2-undefined-subject"),
    (REF.replace("subject_definitions:", "wrong_definitions:"), "S1-missing-section"),
])
def test_official_and_engineering_errors_still_reach_the_caller(text, expected):
    findings = validate(text, Context(n_pictures=1, duration_s=8))
    assert expected in {f.rule for f in findings if f.severity == "ERROR"}


def test_explicit_shot_count_remains_an_enforced_user_constraint():
    findings = validate(BASE, Context(mode="t2va", duration_s=8, pinned_shots=25))
    assert any(f.rule == "T11-shot-count-pinned" and f.severity == "ERROR" for f in findings)


def test_shot_plan_preserves_many_close_cuts_and_free_description():
    raw = {"shots": [{"starts_at_s": i / 1000, "purpose": "poetic pause", "framing": "custom frame",
                      "action": "a candle flickers", "what_changes": "", "camera": {}}
                     for i in range(25)]}
    result = validate_proposal(raw, Target.build(8))
    assert result.ok, result.rejections
    assert [shot.start_ms for shot in result.shots] == list(range(25))
    assert all(shot.purpose == "poetic pause" and shot.framing == "custom frame"
               and shot.what_changes == "" for shot in result.shots)
    assert "maxItems" not in shot_schema()["properties"]["shots"]
    assert shot_schema(exact=25)["properties"]["shots"]["minItems"] == 25


def test_explicit_large_shot_count_survives_intake_and_planning():
    from h3ir.draft import deterministic_draft
    from h3ir.service import BriefIn, _to_brief
    brief = _to_brief(BriefIn(intent="a candle flickers", seconds=8, shots=25))
    assert brief.shots == 25
    assert len(deterministic_draft(brief, Mode.T2VA, {}).shots) == 25


def test_long_director_text_and_name_reach_the_writer():
    import json
    from h3ir.director import from_mapping
    from h3ir.prose import compose_brief
    seen = []
    class Capture:
        def chat(self, messages, **kwargs):
            seen.extend(messages)
            return type("Reply", (), {"content": BASE})()
    notes = "保持天空里的字幕与背景。" * 1000
    director = from_mapping({"name": "用户指定导演", "notes": notes})
    compose_brief(Capture(), Brief(intent="日落时分", seconds=8), [], {}, Target.build(8), (),
                  mode=Mode.T2VA, director=director)
    facts = json.loads(seen[-1]["content"].split("\n\n", 1)[1])
    assert facts["direction_requested"] == {"name": "用户指定导演", "notes": notes}


def test_repair_preserves_task_prefix_unicode_and_out_of_range_media():
    original = REF.replace("[reference generation]", "[video editing]").replace("<Picture 1>", "<Picture 9>")
    original = original.replace("red coat", "child’s coat—蓝色")
    result = repair(original, target=Target.build(8), mode=Mode.REF2VA,
                    labels=("<Picture 1>",), task_types=("reference generation",))
    assert result.text == original
    assert not result.repairs
    assert "L3-phantom-media" in {f.rule for f in validate(result.text, Context(n_pictures=1, duration_s=8))}


def test_repair_does_not_silently_remove_repeated_dialogue():
    line = '<Subject 1> (S1) says <d>[English] Open the door.</d>'
    text = REF.replace("[Shot 1] <Subject 1> opens a door.", f"[Shot 1] {line} [Shot 2] At 00:04.000, {line}")
    result = repair(text, target=Target.build(8), mode=Mode.REF2VA, labels=("<Picture 1>",),
                    dialogue=("Open the door.",))
    assert result.text.count("<d>[English] Open the door.</d>") == 2


def test_compiler_does_not_publish_author_findings():
    from h3ir.compile import compile_brief
    class LocalBackend:
        class cfg:
            model = "local-test"
        def require_available(self): pass
        def server_version(self): return "local-test"
        def close(self): pass
    result = compile_brief(Brief(intent="a child opens a door", seconds=8),
                           backend=LocalBackend(), llm=False)
    assert result.prompt
    assert all(origin(f.rule) != "author" for f in result.findings)


def test_filter_guard_detects_a_simulated_policy_regression(monkeypatch):
    import h3ir.policies as policies
    rule = next(iter(DISABLED_AUTHOR_RULES))
    monkeypatch.setattr(policies, "enabled", lambda rule: True)
    with pytest.raises(AssertionError):
        test_disabled_author_findings_cannot_reach_the_caller(rule)


def test_classification_guard_detects_a_simulated_unregistered_rule(monkeypatch):
    monkeypatch.delitem(OFFICIAL_RULES, "R2-illegal-marker")
    with pytest.raises(AssertionError):
        test_every_emittable_rule_is_explicitly_classified()


def test_image_analysis_preserves_background_labels_and_unlimited_attributes():
    from h3ir.analyse import IMAGE_SCHEMA, analyse_image
    from h3ir.models import AssetKind, AssetRef, Role
    attributes = [f"visible detail {i}" for i in range(15)]
    captured = []
    class Capture:
        class cfg:
            model = "local-test"
        def json_call(self, messages, schema, **kwargs):
            captured.extend(messages)
            return {"summary": "人物设定图，三视图", "subjects": [{"kind": "person", "descriptor": "小画家",
                    "attributes": attributes, "pose": ["双臂展开"]}], "environment": "蓝色网格背景",
                    "visible_text": ["正面", "背面", "侧面"], "is_reference_sheet": True}
    ref = AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256="local-sheet")
    card = analyse_image(Capture(), ref)
    assert card.subjects[0]["attributes"] == attributes
    assert card.environment == "蓝色网格背景"
    assert card.visible_text == ["正面", "背面", "侧面"]
    assert card.is_reference_sheet
    assert "minItems" not in IMAGE_SCHEMA["properties"]["subjects"]["items"]["properties"]["attributes"]
    assert "maxItems" not in IMAGE_SCHEMA["properties"]["subjects"]["items"]["properties"]["attributes"]
    assert "retaining its background" in captured[0]["content"]


def test_shot_plan_preserves_chinese_camera_parameters():
    camera = {"type": "掠水镜头", "amplitude": "从屋檐到海面", "speed": "先慢后快"}
    result = validate_proposal({"shots": [{"starts_at_s": 0, "camera": camera}]}, Target.build(8))
    assert result.ok
    assert result.shots[0].camera == camera
    properties = shot_schema()["properties"]["shots"]["items"]["properties"]["camera"]["properties"]
    assert all("enum" not in schema for schema in properties.values())


@pytest.mark.parametrize("llm", [False, True])
def test_compiler_filters_author_findings_on_each_return_path(monkeypatch, llm):
    import h3ir.compile as compiler
    class LocalBackend:
        class cfg:
            model = "local-test"
        def require_available(self): pass
        def server_version(self): return "local-test"
    author = Finding("S6-style-discrepancy", "WARN", "former author preference")
    engineering = Finding("W16-lora-sha-unverified", "WARN", "unverified weights")
    monkeypatch.setattr(compiler, "resolve_loras", lambda *a: ([], [author, engineering]))
    monkeypatch.setattr(compiler, "compose_brief", lambda *a, **kw: BASE)
    result = compiler.compile_brief(Brief(intent="a child opens a door", seconds=8),
                                    backend=LocalBackend(), llm=llm)
    assert result.source == ("written" if llm else "draft")
    assert engineering in result.findings
    assert author not in result.findings


def test_content_guard_detects_simulated_camera_policy_reactivation(monkeypatch):
    import h3ir.validate as validator
    monkeypatch.setattr(validator, "enabled", lambda rule: True)
    with pytest.raises(AssertionError):
        test_content_is_not_rejected_for_text_camera_unicode_or_length("Live-action, a child opens a door.")


def test_lora_author_suggestions_do_not_override_explicit_caller_choices(monkeypatch):
    from dataclasses import replace
    import h3ir.lora as lora
    records, _, _ = lora.load_registry()
    original = records["handpainted-anim-v2"]
    first = replace(original, id="first", file="", constrains={"aspect": "1:1", "duration_frames": [124]},
                    conflicts_with=("second",))
    second = replace(original, id="second", file="", conflicts_with=("first",))
    monkeypatch.setattr(lora, "load_registry", lambda: ({"first": first, "second": second}, [], "test"))
    selected, findings = lora.resolve_loras([{"id": "first", "strength": 20.0},
                                             {"id": "second", "strength": -3.0}], Mode.REF2VA,
                                            Brief(intent="a painted river", aspect="16:9", seconds=8))
    assert [choice.strength_applied for choice in selected] == [20.0, -3.0]
    assert findings == []


@pytest.mark.parametrize("present,digest,expected", [
    (False, "1" * 64, "W13-lora-file-missing"),
    (True, "1" * 64, "W17-lora-sha-mismatch"),
])
def test_lora_file_integrity_is_still_enforced(monkeypatch, tmp_path, present, digest, expected):
    from dataclasses import replace
    import h3ir.lora as lora
    records, _, _ = lora.load_registry()
    record = replace(records["handpainted-anim-v2"], file="weights.bin", sha256=digest,
                     source_path=str(tmp_path / "howtouse.md"))
    if present:
        (tmp_path / "weights.bin").write_bytes(b"incorrect checkpoint")
    monkeypatch.setattr(lora, "load_registry", lambda: ({record.id: record}, [], "test"))
    selected, findings = lora.resolve_loras([{"id": record.id}], Mode.REF2VA, Brief(intent="a river"))
    assert selected == []
    assert expected in {finding.rule for finding in findings if finding.severity == "ERROR"}


def test_refinement_preserves_large_explicit_duration_and_shot_count():
    from h3ir.compile import refine
    class LocalBackend:
        class cfg:
            model = "local-test"
        def require_available(self): pass
        def server_version(self): return "local-test"
        def json_call(self, messages, schema, **kwargs):
            assert "32秒并分成25个镜头" in messages[-1]["content"]
            return {"intent": "a candle flickers for 32 seconds in 25 shots", "seconds": 32,
                    "shots": 25, "changed": ["seconds", "shots"]}
    result, amended, changed = refine(Brief(intent="a candle flickers", seconds=8),
                                      "延长到32秒并分成25个镜头", backend=LocalBackend(), llm=False)
    assert amended.seconds == 32
    assert amended.shots == 25
    assert len(result.plan.shots) == 25
    assert result.plan.target.effective_seconds >= 32
    assert changed == ["seconds", "shots"]
    assert result.provenance["changed_fields"] == changed
