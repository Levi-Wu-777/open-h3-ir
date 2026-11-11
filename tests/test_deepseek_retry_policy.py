from __future__ import annotations

import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

import h3ir.backend as backend_module
from h3ir.backend import Backend, BackendError, EndpointRefused
from h3ir.config import (DEEPSEEK_MAX_ATTEMPTS, DEEPSEEK_RETRY_DELAY_SECONDS,
                         DEEPSEEK_TIMEOUT_SECONDS, Config, LLMConfig)

MESSAGES = [{"role": "user", "content": "写一段中文。"}]
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}}


def make_backend(handler):
    config = Config(llm=LLMConfig(base_url="https://api.deepseek.com", model="deepseek-flash",
                                 api_key="local-test-only", max_tokens=321, timeout_s=600))
    return Backend(config, client=httpx.Client(transport=httpx.MockTransport(handler)))


def reply(content="完成。", *, finish="stop", usage=None):
    return httpx.Response(200, json={
        "model": "deepseek-flash", "choices": [{"finish_reason": finish, "message": {"content": content}}],
        "usage": usage or {"prompt_tokens": 11, "completion_tokens": 7}})


@pytest.fixture
def recorded_sleeps(monkeypatch):
    sleeps = []
    monkeypatch.setattr(backend_module.time, "sleep", sleeps.append)
    return sleeps


def test_fixed_deepseek_policy_constants():
    assert DEEPSEEK_MAX_ATTEMPTS == 3
    assert DEEPSEEK_RETRY_DELAY_SECONDS == 1
    assert DEEPSEEK_TIMEOUT_SECONDS == 30


def test_other_providers_keep_two_total_attempts_by_default(recorded_sleeps):
    requests = []
    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("local endpoint timed out", request=request)
    config = Config(llm=LLMConfig(base_url="http://127.0.0.1:8000/v1", model="local"))
    backend = Backend(config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(BackendError, match="after 2 attempt"):
        backend.chat(MESSAGES)
    assert len(requests) == 2
    assert recorded_sleeps == [1.5]


@pytest.mark.parametrize("failure", ["429", "500", "503", "connect", "timeout", "empty", "length", "invalid_json"])
def test_failed_chat_has_three_total_attempts_fixed_delay_and_unchanged_token_budget(failure, recorded_sleeps):
    requests = []
    def handler(request):
        requests.append(request)
        if failure in ("429", "500", "503"):
            return httpx.Response(int(failure), json={"error": {"message": "temporary failure"}})
        if failure == "connect":
            raise httpx.ConnectError("network failed", request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("read failed", request=request)
        if failure == "empty":
            return reply("")
        if failure == "length":
            return reply("未完成", finish="length")
        return httpx.Response(200, text="not response JSON")
    with pytest.raises(BackendError):
        make_backend(handler).chat(MESSAGES, max_tokens=77, retries=99)
    assert len(requests) == 3
    assert recorded_sleeps == [1, 1]
    assert [json.loads(request.content)["max_tokens"] for request in requests] == [77, 77, 77]
    assert all(set(request.extensions["timeout"].values()) == {30} for request in requests)


@pytest.mark.parametrize("status", [400, 401, 403])
@pytest.mark.parametrize("structured", [False, True])
def test_permanent_and_authentication_failures_are_not_retried(status, structured, recorded_sleeps):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": "request refused"}})
    backend = make_backend(handler)
    with pytest.raises(EndpointRefused) as caught:
        if structured:
            backend.json_call(MESSAGES, SCHEMA, required=("summary",))
        else:
            backend.chat(MESSAGES)
    assert caught.value.status == status
    assert len(requests) == 1 and not recorded_sleeps


@pytest.mark.parametrize("status", [401, 403])
def test_deepseek_health_authentication_failure_stops_before_another_path(status):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json={"error": {"message": "credential refused"}})
    with pytest.raises(EndpointRefused) as caught:
        make_backend(handler).require_available()
    assert caught.value.status == status
    assert len(requests) == 1 and requests[0].url.path == "/models"


def test_structured_transport_empty_and_parse_failures_share_one_attempt_budget(recorded_sleeps):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return [httpx.Response(503, text="busy"), reply(""), reply('{"summary":"完成"}')][len(requests) - 1]
    result = make_backend(handler).json_call(MESSAGES, SCHEMA, required=("summary",), max_tokens=77)
    assert result == {"summary": "完成"}
    assert len(requests) == 3 and recorded_sleeps == [1, 1]
    assert [request["max_tokens"] for request in requests] == [77, 77, 77]


def test_structured_bad_json_and_missing_keys_use_the_same_three_attempts(recorded_sleeps):
    requests = []
    def handler(request):
        requests.append(request)
        return reply(["not JSON", "{}", '{"summary":"完成"}'][len(requests) - 1])
    result = make_backend(handler).json_call(MESSAGES, SCHEMA, required=("summary",))
    assert result == {"summary": "完成"}
    assert len(requests) == 3 and recorded_sleeps == [1, 1]


def test_structured_retry_exhaustion_never_multiplies_inner_chat_attempts(recorded_sleeps):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(429, text="rate limited")
    with pytest.raises(BackendError, match="after 3 attempt"):
        make_backend(handler).json_call(MESSAGES, SCHEMA, required=("summary",), retries=99)
    assert len(requests) == 3 and recorded_sleeps == [1, 1]


def test_reply_keeps_its_own_full_usage():
    usage = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18,
             "prompt_tokens_details": {"cached_tokens": 5}, "prompt_cache_hit_tokens": 5}
    result = make_backend(lambda request: reply(usage=usage)).chat(MESSAGES)
    assert result.usage == usage
    assert result.prompt_tokens == 11 and result.completion_tokens == 7


def test_retry_wait_is_really_one_second():
    calls = []
    def handler(request):
        calls.append(time.monotonic())
        return httpx.Response(503, text="busy") if len(calls) == 1 else reply()
    assert make_backend(handler).chat(MESSAGES).content == "完成。"
    assert len(calls) == 2 and 0.95 <= calls[1] - calls[0] < 2


def test_total_deadline_cancels_body_after_earlier_network_wait_before_retry(monkeypatch, recorded_sleeps):
    monkeypatch.setattr(backend_module, "DEEPSEEK_TIMEOUT_SECONDS", 1.0)
    calls = []
    events = []
    payload = json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "完成。"}}]}).encode()
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            events.append("body_started")
            try:
                await asyncio.sleep(0.6)
                yield payload
            finally:
                events.append("body_stopped")
        async def aclose(self):
            events.append("response_closed")
    async def handler(request):
        calls.append(time.monotonic())
        if len(calls) == 1:
            await asyncio.sleep(0.6)
            return httpx.Response(200, stream=SlowBody())
        assert events == ["body_started", "body_stopped", "response_closed"]
        await asyncio.sleep(0.2)
        return reply()
    started = time.monotonic()
    result = make_backend(handler).chat(MESSAGES)
    elapsed = time.monotonic() - started
    assert result.content == "完成。" and len(calls) == 2
    assert 0.95 <= calls[1] - calls[0] < 1.2
    assert 1.15 <= elapsed < 1.6
    assert recorded_sleeps == [1]


def test_timeout_exhaustion_keeps_last_error_without_extra_attempts(recorded_sleeps):
    requests = []
    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("request timed out", request=request)
    with pytest.raises(BackendError, match="request timed out"):
        make_backend(handler).json_call(MESSAGES, SCHEMA, required=("summary",))
    assert len(requests) == 3 and recorded_sleeps == [1, 1]


def test_parallel_calls_keep_content_and_usage_attached_to_their_own_reply():
    active = 0
    peak = 0
    lock = threading.Lock()
    async def handler(request):
        nonlocal active, peak
        index = int(json.loads(request.content)["messages"][0]["content"])
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            await asyncio.sleep(0.05)
            return reply(str(index), usage={"prompt_tokens": index, "completion_tokens": index + 1})
        finally:
            with lock:
                active -= 1
    backend = make_backend(handler)
    def call(index):
        return backend.chat([{"role": "user", "content": str(index)}])
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(call, range(1, 9)))
    assert peak == 4 and active == 0
    assert [result.content for result in results] == [str(i) for i in range(1, 9)]
    assert [result.usage["prompt_tokens"] for result in results] == list(range(1, 9))


def test_sync_client_initializes_once_when_analysis_threads_start_together(monkeypatch):
    backend = Backend(Config())
    barrier = threading.Barrier(8)
    constructed = []
    def construct(**kwargs):
        time.sleep(0.02)
        client = object()
        constructed.append(client)
        return client
    monkeypatch.setattr(backend_module.httpx, "Client", construct)
    def get_client(_):
        barrier.wait()
        return backend._http()
    with ThreadPoolExecutor(max_workers=8) as pool:
        clients = list(pool.map(get_client, range(8)))
    assert len(constructed) == 1
    assert all(client is constructed[0] for client in clients)
