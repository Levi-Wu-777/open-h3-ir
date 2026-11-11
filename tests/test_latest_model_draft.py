"""真实编译流程始终交付最近一轮模型稿，不以预制模板替代。"""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

import h3ir.compile as compiler
from h3ir.backend import BackendError
from h3ir.models import Brief, Mode


def _text(version, *, sound=True):
    return (f"integrated_multimodal_description:\n[Shot 1] Live-action, {version} opens a door.\n\n"
            + ("overall_soundscape:\nA latch clicks.\n\n" if sound else "")
            + "non_diegetic_music:\nN/A\n")


class ScriptedBackend:
    cfg = SimpleNamespace(model="local-test")

    def __init__(self, *responses):
        self.responses = list(responses)
        self.messages = []

    def require_available(self):
        pass

    def server_version(self):
        return "local-test"

    def chat(self, messages, **kwargs):
        self.messages.append(deepcopy(messages))
        if not self.responses:
            raise AssertionError("the compiler exceeded the supplied model calls")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(content=response)


def _compile(backend):
    return compiler.compile_brief(Brief(intent="a person opens a door", seconds=8, mode=Mode.T2VA),
                                  backend=backend)


def test_two_unsuccessful_revisions_return_c_and_send_b_into_the_second_revision():
    first, second = [_text(version, sound=False) for version in ("Alice", "Beatrice")]
    final = _text("Cora").replace("[Shot 1]", "[Shot 1] At 00:00.000,")
    backend = ScriptedBackend(first, second, final)
    doc = _compile(backend)
    assert doc.prompt == final
    assert doc.sections["integrated_multimodal_description"].strip().endswith("Cora opens a door.")
    assert doc.source == "written"
    assert doc.fallback_reason is None
    assert doc.fell_back is False
    assert doc.ok is False
    assert {finding.rule for finding in doc.errors} == {"T2-shot1-timestamp"}
    assert doc.provenance["fix_rounds"] == 2
    assert len(backend.messages) == 3
    assert "YOUR TEXT\n" + first in backend.messages[1][-1]["content"]
    assert "YOUR TEXT\n" + second in backend.messages[2][-1]["content"]
    assert "Alice opens a door" not in backend.messages[2][-1]["content"]


@pytest.mark.parametrize("completed_revisions", [0, 1])
def test_revision_endpoint_failure_preserves_the_latest_available_model_draft(completed_revisions):
    drafts = [_text("Alice", sound=False), _text("Beatrice", sound=False)]
    failure = BackendError("revision endpoint unavailable")
    backend = ScriptedBackend(*drafts[:completed_revisions + 1], failure)
    doc = _compile(backend)
    assert doc.prompt == drafts[completed_revisions]
    assert doc.source == "written"
    assert doc.fallback_reason is None
    assert not doc.fell_back
    assert not doc.ok
    assert "S1-missing-section" in {finding.rule for finding in doc.errors}
    assert any("revision endpoint unavailable" in finding.msg for finding in doc.findings)
    assert len(backend.messages) == completed_revisions + 2


def test_initial_endpoint_failure_propagates_the_original_exception_without_a_draft():
    failure = BackendError("initial completion unavailable")
    backend = ScriptedBackend(failure)
    with pytest.raises(BackendError) as raised:
        _compile(backend)
    assert raised.value is failure
    assert len(backend.messages) == 1


def test_warning_only_output_is_delivered_without_revision():
    written = _text("Alice").replace("A latch clicks.", "One rings. Two ring. Three ring. Four ring. Five ring.")
    backend = ScriptedBackend(written)
    doc = _compile(backend)
    assert doc.prompt == written
    assert doc.ok
    assert doc.source == "written"
    assert doc.fallback_reason is None
    assert "A1-soundscape-length" in {finding.rule for finding in doc.warnings}
    assert doc.provenance["fix_rounds"] == 0
    assert len(backend.messages) == 1


@pytest.mark.parametrize("revision_count", [0, 1, 2])
def test_a_passing_model_draft_is_delivered_at_the_first_passing_round(revision_count):
    broken = [_text(version, sound=False) for version in ("Alice", "Beatrice")]
    passed = _text("Cora")
    backend = ScriptedBackend(*broken[:revision_count], passed)
    doc = _compile(backend)
    assert doc.prompt == passed
    assert doc.ok
    assert doc.source == "written"
    assert doc.fallback_reason is None
    assert doc.provenance["fix_rounds"] == revision_count
    assert len(backend.messages) == revision_count + 1


def test_default_writer_is_not_blocked_by_a_precomputed_template(monkeypatch):
    import h3ir.draft as draft
    def forbidden(*args, **kwargs):
        raise AssertionError("the default writer must not precompute or validate a template")
    monkeypatch.setattr(compiler, "deterministic_draft", forbidden, raising=False)
    monkeypatch.setattr(draft, "deterministic_draft", forbidden)
    monkeypatch.setattr(compiler, "_assess", forbidden, raising=False)
    backend = ScriptedBackend(_text("Alice"))
    doc = _compile(backend)
    assert doc.prompt == _text("Alice")
    assert doc.ok
    assert len(backend.messages) == 1


class EnrichmentBackend(ScriptedBackend):
    def __init__(self, *responses, objects=()):
        super().__init__(*responses)
        self.objects = list(objects)

    def json_call(self, messages, *args, **kwargs):
        response = self.objects.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_optional_enrichment_delivers_its_actual_text_and_errors():
    plan = {"shots": [{"starts_at_s": 0, "purpose": "reveal", "framing": "wide",
                        "action": "Cora opens a door", "what_changes": "", "camera": {}}]}
    beats = {"shots": [{"beat": "Cora opens a door", "subjects": [], "sync_sound": [], "camera": {}}],
             "ambient_sound": ["A latch clicks."], "style_phrase": "Live-action",
             "summary": "Cora opens a door.", "music": "N/A"}
    backend = EnrichmentBackend("Cora opens a door. <d>[English] Unfinished line.", objects=[plan, beats])
    doc = compiler.compile_brief(Brief(intent="a person opens a door", seconds=8, mode=Mode.T2VA),
                                  backend=backend, write_first=False)
    assert doc.source == "enriched"
    assert doc.fallback_reason is None
    assert not doc.fell_back
    assert "cora opens a door." in doc.prompt.lower()
    assert "<d>[English] Unfinished line." in doc.prompt
    assert not doc.ok
    assert "D1-unbalanced-d" in {finding.rule for finding in doc.errors}


def test_optional_enrichment_failure_before_any_prose_propagates():
    failure = BackendError("shot planner unavailable")
    backend = EnrichmentBackend(objects=[failure])
    with pytest.raises(BackendError) as raised:
        compiler.compile_brief(Brief(intent="a person opens a door", seconds=8, mode=Mode.T2VA),
                               backend=backend, write_first=False)
    assert raised.value is failure
    assert backend.messages == []
