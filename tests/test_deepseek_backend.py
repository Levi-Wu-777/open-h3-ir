"""DeepSeek 兼容协议与凭据配置；全部 HTTP 均在本地模拟。"""
from __future__ import annotations

import json
import sys
import types

import httpx
import pytest

from h3ir.backend import Backend, EndpointRefused, TruncatedResponse
from h3ir.config import Config, LLMConfig


@pytest.fixture
def infisical(monkeypatch):
    package = types.ModuleType("share")
    module = types.ModuleType("share.infisical")
    module.read_secret = lambda path, name: "test-only-key"
    package.infisical = module
    monkeypatch.setitem(sys.modules, "share", package)
    monkeypatch.setitem(sys.modules, "share.infisical", module)
    return module


def _backend(handler, *, url="https://api.deepseek.com", thinking=False):
    cfg = Config(llm=LLMConfig(base_url=url, model="deepseek-flash", api_key="test-only-key",
                               default_thinking=thinking, max_tokens=100))
    return Backend(cfg=cfg, client=httpx.Client(transport=httpx.MockTransport(handler)))


def _response(content="你好，世界。", **extra):
    return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
        "content": content, **extra}}], "usage": {"prompt_tokens": 11, "completion_tokens": 7}})


@pytest.mark.parametrize("url", ["https://api.deepseek.com", "https://api.deepseek.com/v1"])
@pytest.mark.parametrize("thinking", [False, True])
def test_deepseek_uses_native_thinking_auth_and_preserves_chinese(url, thinking):
    captured = []
    def handler(request):
        captured.append(request)
        return _response(reasoning_content="思考过程" if thinking else "")
    backend = _backend(handler, url=url)
    reply = backend.chat([{"role": "user", "content": "请生成中文场景：小松鼠穿过雨林。"}],
                         thinking=thinking, seed=42, temperature=0.3, max_tokens=77, retries=0)
    assert reply.content == "你好，世界。"
    request = captured[0]
    body = json.loads(request.content)
    assert str(request.url) == url + "/chat/completions"
    assert request.headers["Authorization"] == "Bearer test-only-key"
    assert body["model"] == "deepseek-flash"
    assert body["thinking"] == {"type": "enabled" if thinking else "disabled"}
    assert "chat_template_kwargs" not in body
    assert "seed" not in body
    assert body["messages"][0]["content"] == "请生成中文场景：小松鼠穿过雨林。"
    assert body["max_tokens"] == 77
    assert body["temperature"] == 0.3


def test_deepseek_uses_disabled_thinking_by_default():
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return _response()
    _backend(handler).chat([{"role": "user", "content": "你好"}], retries=0)
    assert seen[0]["thinking"] == {"type": "disabled"}


def test_existing_openai_compatible_endpoints_keep_their_protocol():
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return _response()
    backend = _backend(handler, url="http://127.0.0.1:8000/v1")
    backend.chat([{"role": "user", "content": "hello"}], thinking=False, seed=9, retries=0)
    assert seen[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert seen[0]["seed"] == 9
    assert "thinking" not in seen[0]


def test_deepseek_json_calls_parse_chinese_content_and_send_response_format():
    seen = []
    def handler(request):
        seen.append(json.loads(request.content))
        return _response('{"summary":"雨林中的松鼠"}')
    reply = _backend(handler).chat([{"role": "user", "content": "返回JSON"}],
                                  response_format={"type": "json_object"}, retries=0)
    assert json.loads(reply.content) == {"summary": "雨林中的松鼠"}
    assert seen[0]["response_format"] == {"type": "json_object"}


def test_deepseek_auth_failure_is_loud_and_not_retried():
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(401, json={"error": {"message": "invalid api key"}})
    with pytest.raises(EndpointRefused, match="invalid api key"):
        _backend(handler).chat([{"role": "user", "content": "hello"}])
    assert len(seen) == 1


def test_deepseek_incomplete_answer_is_not_treated_as_a_valid_prompt():
    def handler(request):
        return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {
            "content": "未完成的中文"}}]})
    with pytest.raises(TruncatedResponse, match="incomplete"):
        _backend(handler).chat([{"role": "user", "content": "hello"}], retries=0)


def test_configuration_reads_exactly_one_infisical_secret_and_keeps_other_settings(monkeypatch, infisical):
    import h3ir.deepseek as deepseek
    calls = []
    original = Config(llm=LLMConfig(base_url="http://old/v1", model="old", max_tokens=321),
                      profile="test-profile")
    def read_secret(path, name):
        calls.append((path, name))
        return "infisical-test-only-key"
    monkeypatch.setattr(infisical, "read_secret", read_secret)
    monkeypatch.setattr(deepseek, "get_config", lambda: original)
    cfg = deepseek.configure_deepseek()
    assert calls == [("/accounts/deepseek", "DEEPSEEK_API_KEY")]
    assert cfg.llm.base_url == "https://api.deepseek.com"
    assert cfg.llm.model == "deepseek-flash"
    assert cfg.llm.api_key == "infisical-test-only-key"
    assert cfg.llm.default_thinking is False
    assert cfg.llm.max_tokens == 321
    assert cfg.profile == "test-profile"
    seen = []
    def handler(request):
        seen.append(request)
        return _response()
    backend = Backend(cfg=cfg, client=httpx.Client(transport=httpx.MockTransport(handler)))
    backend.chat([{"role": "user", "content": "你好"}], retries=0)
    backend.chat([{"role": "user", "content": "继续"}], retries=0)
    assert len(calls) == 1
    assert all(request.headers["authorization"] == "Bearer infisical-test-only-key" for request in seen)
    assert original.llm.model == "old"


def test_configuration_does_not_swallow_missing_credentials(monkeypatch, infisical):
    from h3ir.deepseek import configure_deepseek
    def unavailable(*args):
        raise RuntimeError("secret unavailable")
    monkeypatch.setattr(infisical, "read_secret", unavailable)
    with pytest.raises(RuntimeError, match="secret unavailable"):
        configure_deepseek()


def test_wire_guard_detects_a_simulated_thinking_regression(monkeypatch):
    original = Backend._once
    def mutated(self, body):
        body["thinking"] = {"type": "enabled"}
        return original(self, body)
    monkeypatch.setattr(Backend, "_once", mutated)
    with pytest.raises(AssertionError):
        test_deepseek_uses_disabled_thinking_by_default()
