from __future__ import annotations

from dataclasses import replace

import pytest
from starlette.testclient import TestClient

from h3ir import cli, service
from h3ir.backend import BackendError, BackendUnavailable
from h3ir.compile import BriefRefused
from h3ir.grid import Target
from h3ir.models import Finding, IRDocument, Mode, Plan, ShotPlan


@pytest.fixture(autouse=True)
def isolate_service_store(monkeypatch):
    monkeypatch.setattr(service, "_STORE", {})


def make_document(source="written", rule="S1-missing-section"):
    plan = Plan(mode=Mode.T2VA, target=Target.build(5), manifest=[], subjects=[], speakers=[],
                shots=[ShotPlan(n=1, start_ms=0, end_ms=5167)], task_types=[])
    return IRDocument(ir_version="test", profile="test", mode=Mode.T2VA,
                      prompt="最后一轮模型稿，保留尚未解决的问题。\n", plan=plan, sections={},
                      source=source, fallback_reason=None,
                      findings=[Finding(rule, "ERROR", "原始错误说明")],
                      provenance={"timings": {}, "request": "原始请求"})


@pytest.mark.parametrize("source", ["written", "enriched"])
@pytest.mark.parametrize("rule", ["S1-missing-section", "T6-time-past-end"])
def test_api_delivers_model_text_with_original_error_diagnostics(source, rule, monkeypatch):
    doc = make_document(source, rule)
    monkeypatch.setattr(service, "compile_brief", lambda *args, **kwargs: doc)
    client = TestClient(service.app)
    created = client.post("/v1/briefs", json={"intent": "原始请求"})
    assert created.status_code == 201, created.text
    response = created.json()
    assert response["status"] == "needs_review"
    assert response["source"] == source and response["fallback_reason"] is None
    assert response["ir"]["prompt"] == doc.prompt
    assert response["ir"]["diagnostics"] == [
        {"rule": rule, "severity": "ERROR", "message": "原始错误说明"}]
    assert response["errors"] == [{"rule": rule, "message": "原始错误说明"}]
    assert not doc.ok and len(doc.errors) == 1 and not doc.warnings and not doc.fell_back
    assert "unresolved validation diagnostics" in response["presentation"]["notice"]
    assert "degraded" not in response["presentation"]
    fetched = client.get(f"/v1/briefs/{response['id']}")
    assert fetched.status_code == 200 and fetched.json() == response
    prompt = client.get(f"/v1/briefs/{response['id']}/prompt")
    assert prompt.status_code == 200 and prompt.json()["prompt"] == doc.prompt


@pytest.mark.parametrize("source", ["written", "enriched"])
def test_refine_delivers_model_diagnostics_and_get_keeps_review_status(source, monkeypatch):
    initial = replace(make_document(), findings=[])
    amended = make_document(source)
    amended.prompt = "修改后的最后模型稿。\n"
    monkeypatch.setattr(service, "compile_brief", lambda *args, **kwargs: initial)
    monkeypatch.setattr(service, "refine", lambda brief, change, **kwargs: (amended, brief, ["intent"]))
    client = TestClient(service.app)
    created = client.post("/v1/briefs", json={"intent": "原始请求"})
    assert created.json()["status"] == "ready"
    brief_id = created.json()["id"]
    refined = client.patch(f"/v1/briefs/{brief_id}", json={"change": "调整动作"})
    assert refined.status_code == 200
    response = refined.json()
    assert response["status"] == "needs_review"
    assert response["ir"]["prompt"] == amended.prompt
    assert response["ir"]["diagnostics"][0]["severity"] == "ERROR"
    assert response["changed"] == ["intent"] and response["version"] == 2
    fetched = client.get(f"/v1/briefs/{brief_id}").json()
    assert fetched == {k: v for k, v in response.items() if k not in ("changed", "version")}


def test_review_status_preserves_clarification_without_hiding_diagnostics(monkeypatch):
    doc = make_document()
    doc.provenance["clarification"] = {"question": "Which opening frame?", "default_if_unanswered": "reference"}
    monkeypatch.setattr(service, "compile_brief", lambda *args, **kwargs: doc)
    response = TestClient(service.app).post("/v1/briefs", json={"intent": "原始请求"}).json()
    assert response["status"] == "needs_review"
    assert response["question"] == doc.provenance["clarification"]
    assert response["default_if_unanswered"] == "reference"


@pytest.mark.parametrize("rule,status", [("S1-missing-section", 500), ("T6-time-past-end", 422)])
def test_non_model_invalid_document_still_fails_delivery(rule, status, monkeypatch):
    doc = make_document(source="draft", rule=rule)
    monkeypatch.setattr(service, "compile_brief", lambda *args, **kwargs: doc)
    monkeypatch.setattr(service, "refine", lambda brief, change, **kwargs: (doc, brief, []))
    client = TestClient(service.app)
    response = client.post("/v1/briefs", json={"intent": "原始请求"})
    assert response.status_code == status
    assert response.json()["status"] == "invalid"
    brief_id = response.json()["id"]
    changed = client.patch(f"/v1/briefs/{brief_id}", json={"change": "调整动作"})
    assert changed.status_code == status and changed.json()["status"] == "invalid"


@pytest.mark.parametrize("error,status,code", [
    (BriefRefused("intent-empty", "请求为空"), 422, "intent-empty"),
    (BackendUnavailable("没有模型结果"), 503, "llm-unavailable"),
    (BackendError("没有模型结果"), 502, "llm-error"),
])
def test_input_or_backend_failure_without_a_document_keeps_real_http_error(error, status, code, monkeypatch):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(service, "compile_brief", fail)
    client = TestClient(service.app)
    response = client.post("/v1/briefs", json={"intent": "原始请求"})
    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert service._STORE == {}


@pytest.mark.parametrize("source", ["written", "enriched"])
def test_cli_writes_model_text_and_exits_zero_without_hiding_errors(source, monkeypatch, tmp_path, capsys):
    from h3ir import compile as compiler
    doc = make_document(source)
    monkeypatch.setattr(compiler, "compile_brief", lambda *args, **kwargs: doc)
    output = tmp_path / "prompt.txt"
    assert cli.main(["compile", "原始请求", "--out", str(output)]) == 0
    assert output.read_text() == doc.prompt
    printed = capsys.readouterr().out
    assert "S1-missing-section" in printed and "原始错误说明" in printed
    assert doc.prompt in printed and not doc.ok


def test_cli_keeps_failure_exit_for_non_model_invalid_document(monkeypatch, capsys):
    from h3ir import compile as compiler
    monkeypatch.setattr(compiler, "compile_brief", lambda *args, **kwargs: make_document("draft"))
    assert cli.main(["compile", "原始请求"]) == 1
    assert "S1-missing-section" in capsys.readouterr().out
