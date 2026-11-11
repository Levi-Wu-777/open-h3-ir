from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from h3ir import cli, contract, service
from h3ir.compile import amend_brief, compile_brief
from h3ir.grid import Target
from h3ir.models import Brief, DialogueLine, Finding, Mode, ShotPlan
from h3ir.prose import beat_schema, beat_sheet, compose_brief, fix_with_findings, plan_shots, shot_body
from h3ir.validate import Context, validate

CHINESE = '''integrated_multimodal_description:
[Shot 1] 写实影像，柔和晨光照进车站。镜头缓慢推进，旅客抬头说 (S1) <d>[English] Wait for me.</d>，身后的招牌写着 "OPEN"。

overall_soundscape:
车轮轻响，远处传来候车大厅的广播。

non_diegetic_music:
N/A
'''


class CaptureBackend:
    cfg = SimpleNamespace(model="local-test")

    def __init__(self, replies=(), objects=()):
        self.replies = iter(replies)
        self.objects = iter(objects)
        self.messages = []

    def require_available(self):
        pass

    def server_version(self):
        return "local-test"

    def chat(self, messages, **kwargs):
        self.messages.append(messages)
        return SimpleNamespace(content=next(self.replies))

    def json_call(self, messages, *args, **kwargs):
        self.messages.append(messages)
        return next(self.objects)


def make_brief(language="zh-CN"):
    return Brief(intent="一位旅客在车站等朋友", prompt_language=language,
                 mode=Mode.T2VA, dialogue=[DialogueLine("Wait for me.")],
                 onscreen_text=["OPEN"])


@pytest.mark.parametrize("language", ["zh-CN", "中文", "auto", "Français"])
def test_api_accepts_and_forwards_free_language(language, monkeypatch):
    seen = []

    def local_compile(brief, **kwargs):
        seen.append(brief)
        return compile_brief(brief, backend=CaptureBackend([CHINESE]), use_cache=False)

    monkeypatch.setattr(service, "compile_brief", local_compile)
    response = TestClient(service.app).post("/v1/briefs", json={
        "intent": "一位旅客在车站等朋友", "prompt_language": language,
        "dialogue": [{"text": "Wait for me."}], "onscreen_text": ["OPEN"]})
    assert response.status_code == 201, response.text
    assert seen[0].prompt_language == language
    assert response.json()["ir"]["provenance"]["prompt_language"] == language
    assert "<d>[English] Wait for me.</d>" in response.json()["ir"]["prompt"]


def test_language_defaults_and_contract():
    assert Brief("a station").prompt_language == "English"
    assert service.BriefIn(intent="a station").prompt_language == "English"
    assert cli.build_parser().parse_args(["compile", "a station"]).prompt_language == "English"
    assert tuple(service.BriefIn.model_fields) == contract.BRIEF_FIELDS


def test_cli_passes_selected_language(monkeypatch, capsys):
    from h3ir import compile as compiler
    seen = []

    def local_compile(brief, **kwargs):
        seen.append(brief)
        return compile_brief(brief, backend=CaptureBackend([CHINESE]), use_cache=False)

    monkeypatch.setattr(compiler, "compile_brief", local_compile)
    assert cli.main(["compile", "一位旅客在车站等朋友", "--prompt-language", "中文"]) == 0
    assert seen[0].prompt_language == "中文"
    assert "车轮轻响" in capsys.readouterr().out


@pytest.mark.parametrize("language", ["English", "zh-CN", "中文", "Français", "auto"])
def test_composer_appends_language_override_after_official_guide(language):
    backend = CaptureBackend([CHINESE])
    compose_brief(backend, make_brief(language), [], {}, Target.build(5), (), mode=Mode.T2VA)
    assert len(backend.messages) == 1
    system = backend.messages[0][0]["content"]
    override = system.split("CALLER'S OUTPUT LANGUAGE", 1)[1]
    assert "takes precedence over guide instructions to write English" in override
    if language == "auto":
        assert "original request" in override
    else:
        assert language in override
    for literal in ("[Shot N]", "At MM:SS.mmm", "<d>", "enum values", "section keys"):
        assert literal in override
    assert "dialogue and on-screen text verbatim" in override
    assert "do not translate" in override
    raw = backend.messages[0][-1]["content"]
    user = raw if isinstance(raw, str) else raw[0]["text"]
    assert json.loads(user[user.index("{"):])["prompt_language"] == language
    assert "Wait for me." in user and "OPEN" in user


def test_compile_correction_keeps_language_and_verbatim_words():
    broken = CHINESE.replace("overall_soundscape:\n车轮轻响，远处传来候车大厅的广播。\n\n", "")
    backend = CaptureBackend([broken, CHINESE])
    doc = compile_brief(make_brief(), backend=backend, use_cache=False)
    assert doc.ok and doc.source == "written", [str(f) for f in doc.findings]
    assert doc.provenance["fix_rounds"] == 1
    assert len(backend.messages) == 2
    for messages in backend.messages:
        assert '"zh-CN"' in messages[0]["content"]
        assert "do not translate" in messages[0]["content"]
    assert "Wait for me." in doc.prompt and '"OPEN"' in doc.prompt
    assert not {f.rule for f in doc.findings} & {"P2-too-short", "P3-too-long"}


def test_chinese_cut_prefix_correction_keeps_real_times_and_chinese_prose():
    cuts = ("\n[Shot 2] 在 00:00.700，镜头切到旅客的手。"
            "\n[Shot 3] 在 00:02.200，镜头切到站台时钟。"
            "\n[Shot 4] 在 00:02.800，镜头切回旅客身后。")
    broken = CHINESE.replace("\n\noverall_soundscape:", cuts + "\n\noverall_soundscape:")
    corrected = broken.replace("] 在 ", "] At ")
    before = validate(broken, Context(mode="t2va"))
    errors = [f for f in before if f.rule == "T4-missing-cut-time"]
    assert len(errors) == 3
    assert all("literal" in f.msg and "replace a translated prefix" in f.msg for f in errors)
    assert not [f for f in validate(corrected, Context(mode="t2va"))
                if f.rule == "T4-missing-cut-time"]

    backend = CaptureBackend([broken, corrected])
    doc = compile_brief(make_brief(), backend=backend, use_cache=False)
    assert doc.ok and doc.source == "written"
    assert doc.provenance["fix_rounds"] == 1
    for messages in backend.messages:
        assert "never translate it to 在" in messages[0]["content"]
        assert "[Shot 1] has no timestamp" in messages[0]["content"]
    for number, timestamp in ((2, "00:00.700"), (3, "00:02.200"), (4, "00:02.800")):
        assert f"[Shot {number}] At {timestamp}" in doc.prompt
    assert "镜头切回旅客身后" in doc.prompt
    assert "Wait for me." in doc.prompt and '"OPEN"' in doc.prompt


def test_optional_shot_pipeline_passes_language_to_every_call():
    brief = make_brief("中文")
    shot = ShotPlan(n=1, start_ms=0, end_ms=5167, dialogue=brief.dialogue)
    proposal = {"shots": [{"purpose": "establish", "framing": "wide", "action": "旅客等候",
                           "what_changes": "旅客抬头", "starts_at_s": 0, "camera": {}}],
                "reasoning": "一个完整动作"}
    beats = {"shots": [{"beat": "旅客抬头", "camera": {}, "subjects": [], "sync_sound": []}],
             "ambient_sound": ["车轮轻响"], "style_phrase": "写实", "summary": "旅客等候", "music": "N/A"}
    backend = CaptureBackend(["旅客抬头，{{D1}}。"], [proposal, beats])
    assert plan_shots(backend, brief, [], {}, Target.build(5)).ok
    assert beat_sheet(backend, brief, Mode.T2VA, [], {}, [shot])["summary"] == "旅客等候"
    assert "{{D1}}" in shot_body(backend, brief, Mode.T2VA, shot, [], "写实")
    assert len(backend.messages) == 3
    assert all('"中文"' in messages[0]["content"] for messages in backend.messages)


def test_beat_camera_schema_accepts_free_camera_words():
    camera = beat_schema(1)["properties"]["shots"]["items"]["properties"]["camera"]
    for name in ("type", "amplitude", "speed"):
        assert camera["properties"][name] == {"type": "string"}


@pytest.mark.parametrize("camera", [
    {"type": "Crane upward", "amplitude": "medium", "speed": "variable"},
    {"type": "镜头绕人物旋转并升高", "amplitude": "逐渐增大", "speed": "先慢后快"},
])
def test_beat_sheet_keeps_free_camera_words(camera):
    brief = make_brief("中文")
    beats = {"shots": [{"beat": "旅客抬头", "camera": camera, "subjects": [], "sync_sound": []}],
             "ambient_sound": [], "style_phrase": "写实", "summary": "旅客等候", "music": "N/A"}
    backend = CaptureBackend(objects=[beats])
    shot = ShotPlan(n=1, start_ms=0, end_ms=5167)
    result = beat_sheet(backend, brief, Mode.T2VA, [], {}, [shot])
    assert result["shots"][0]["camera"] == camera
    assert '"中文"' in backend.messages[0][0]["content"]


def test_direct_correction_accepts_language_and_preserves_structural_instructions():
    backend = CaptureBackend([CHINESE])
    fix_with_findings(backend, "broken", [Finding("S1-missing-section", "ERROR", "missing section")],
                      prompt_language="中文", sections=("overall_soundscape",))
    assert '"中文"' in backend.messages[0][0]["content"]
    assert "Required 1 sections: overall_soundscape" in backend.messages[0][1]["content"]


def test_refinement_keeps_language_and_user_words():
    brief = make_brief()
    backend = CaptureBackend(objects=[{"intent": "同一旅客在夜间车站等候", "changed": ["intent"]}])
    amended, changed = amend_brief(brief, "改成夜晚", backend)
    assert changed == ["intent"]
    assert amended.prompt_language == "zh-CN"
    assert amended.dialogue == brief.dialogue
    assert amended.onscreen_text == brief.onscreen_text


@pytest.mark.parametrize("description", ["旅客抬头。", "旅客抬头。 " * 800])
def test_chinese_prose_has_no_english_word_count_requirement(description):
    text = ("subject_definitions:\nN/A\nsummary:\n[reference generation] 旅客等候。\n"
            "retention_analysis:\nN/A\ndetailed_description:\n写实影像。\n[Shot 1] "
            + description + "\noverall_soundscape:\n车轮轻响。\nnon_diegetic_music:\nN/A\n")
    assert not {f.rule for f in validate(text, Context())} & {"P2-too-short", "P3-too-long"}


def test_chinese_editing_summary_preserves_official_source_opening():
    text = ("subject_definitions:\n<Video 1> 是原始街景。\nsummary:\n"
            "[video editing] The target video is an edited version of <Video 1>. 将街景改为雨夜。\n"
            "retention_analysis:\n<Video 1>: partially_copy - 保留人物动作。\n"
            "detailed_description:\n写实影像。\n[Shot 1] 原始街景中的人物沿街步行。\n"
            "overall_soundscape:\n雨声。\nnon_diegetic_music:\nN/A\n")
    context = Context(n_videos=1, prompt_language="zh-CN")
    assert not {f.rule for f in validate(text, context)} & {"M5-editing-without-video", "M6-editing-opening"}
    missing_source = text.replace("The target video is an edited version of <Video 1>. ", "")
    assert "M6-editing-opening" in {f.rule for f in validate(missing_source, context)}
    backend = CaptureBackend([text])
    compose_brief(backend, make_brief(), [], {}, Target.build(5), ("<Video 1>",))
    assert "The target video is an edited version of <Video N>." in backend.messages[0][0]["content"]
    assert "never omit the source" in backend.messages[0][0]["content"]


@pytest.mark.parametrize("parts,wording", [
    (("我明天", "就回家。"), "我明天就回家。"),
    (("Hello", "world."), "Hello world."),
    (("你好", "hello", "world。"), "你好hello world。"),
])
def test_split_dialogue_preserves_original_word_boundaries(parts, wording):
    from h3ir.repair import repair
    shots = []
    for index, part in enumerate(parts, 1):
        timestamp = "" if index == 1 else f"At 00:0{index - 1}.000, <scenetrans> "
        ending = " <scenetrans> 声音无缝延续。" if index < len(parts) else ""
        shots.append(f"[Shot {index}] {timestamp}旅客 (S1) 说：<d>[Chinese] {part}</d>{ending}")
    text = ("integrated_multimodal_description:\n" + "\n".join(shots)
            + "\noverall_soundscape:\n车轮轻响。\nnon_diegetic_music:\nN/A\n")
    result = repair(text, target=Target.build(5), mode=Mode.T2VA, labels=(), dialogue=(wording,))
    assert result.text == text
    found = validate(result.text, Context(mode="t2va", prompt_language="zh-CN", expected_dialogue=(wording,)))
    assert not {f.rule for f in found} & {"D4-dialogue-not-verbatim", "D11-split-line-no-scenetrans", "D12-split-line-no-continuity-statement"}
    wrong = text.replace(parts[-1], "改错内容")
    assert "D4-dialogue-not-verbatim" in {f.rule for f in validate(
        wrong, Context(mode="t2va", prompt_language="zh-CN", expected_dialogue=(wording,)))}


def test_non_english_voiceover_keeps_lips_guidance_without_english_lexical_rejection():
    text = CHINESE.replace("旅客抬头说 (S1)", "旅客 (S1) says in an off-screen voiceover:")
    text = text.replace("</d>，", "</d>，画面中旅客的嘴唇保持闭合，")
    assert "D9-voiceover-no-lips-clause" in {f.rule for f in validate(text, Context(mode="t2va"))}
    assert "D9-voiceover-no-lips-clause" not in {
        f.rule for f in validate(text, Context(mode="t2va", prompt_language="zh-CN"))}
    backend = CaptureBackend([text])
    doc = compile_brief(make_brief(), backend=backend, use_cache=False)
    assert doc.ok and doc.source == "written"
    assert "lips remain closed after every voiceover block" in backend.messages[0][0]["content"]


@pytest.mark.parametrize("header", [
    "<Subject 1>（出现在 [Shot 1]、[Shot 2]）：",
    "<Subject 1> (出现在 [Shot 1])：",
    "<Subject 1>（出现在 [Shot 1]）:",
    "<Subject 1>：",
])
def test_retention_parser_accepts_equivalent_chinese_punctuation(header):
    from h3ir.repair import repair
    body = "fully_preserved - 保留衣服（蓝色：棉布）、表情与原文“你好”。"
    text = ("subject_definitions:\n<Subject 1> 是 <Picture 1> 中的旅客（身穿蓝衣）。\n"
            "summary:\n[reference generation] 旅客等候。\nretention_analysis:\n"
            + header + body + "\ndetailed_description:\n写实影像。\n"
            "[Shot 1] 旅客看着招牌“营业中（全天：开放）”。\n"
            "overall_soundscape:\n广播说“你好（请注意：站台）”。\nnon_diegetic_music:\nN/A\n")
    context = Context(n_pictures=1, prompt_language="zh-CN")
    assert not {f.rule for f in validate(text, context)} & {"R1-malformed-entry", "R2-illegal-marker"}
    result = repair(text, target=Target.build(5), mode=Mode.REF2VA, labels=("<Picture 1>",))
    assert result.text == text
    assert not result.repairs


@pytest.mark.parametrize("entry,rule", [
    ("<Subject 1>（出现在 [Shot 1]） fully_preserved - 保留蓝衣。", "R1-malformed-entry"),
    ("<Subject 1>（出现在 [Shot 1]）：完全保留 - 保留蓝衣。", "R2-illegal-marker"),
    ("<Subject 1>（出现在 [Shot 1]）：invented_relation - 保留蓝衣。", "R2-illegal-marker"),
])
def test_retention_punctuation_support_keeps_structure_and_marker_checks(entry, rule):
    text = ("subject_definitions:\n<Subject 1> 是 <Picture 1> 中的旅客。\n"
            "summary:\n[reference generation] 旅客等候。\nretention_analysis:\n"
            + entry + "\ndetailed_description:\n写实影像。\n[Shot 1] 旅客等候。\n"
            "overall_soundscape:\n车轮轻响。\nnon_diegetic_music:\nN/A\n")
    assert rule in {f.rule for f in validate(text, Context(n_pictures=1, prompt_language="zh-CN"))}
