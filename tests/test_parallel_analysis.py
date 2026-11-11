"""素材分析实际重叠、并发上限、顺序与错误传播。"""
from __future__ import annotations

from collections import Counter
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest

from h3ir import analyse
from h3ir.models import AssetCard, AssetKind, AssetRef, Role


def make_ref(digest):
    return AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256=digest)


def test_four_analyses_overlap_and_preserve_input_order(monkeypatch):
    barrier = Barrier(4)
    lock = Lock()
    active = 0
    peak = 0
    refs = [make_ref(str(index)) for index in range(6)]

    def analyse_image(backend, ref, **kwargs):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            if int(ref.sha256) < 4:
                barrier.wait(timeout=3)
            return AssetCard(sha256=ref.sha256, kind=ref.kind, summary=ref.sha256)
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(analyse, "analyse_image", analyse_image)
    backend = SimpleNamespace(cfg=SimpleNamespace(model="test"))
    cards = analyse.analyse_all(backend, refs, use_cache=False)
    assert peak == 4
    assert list(cards) == [ref.sha256 for ref in refs]
    assert [card.summary for card in cards.values()] == [ref.sha256 for ref in refs]


def test_duplicate_cached_assets_share_work_and_cache_writes(monkeypatch):
    calls = Counter()
    saved = []

    def analyse_image(backend, ref, **kwargs):
        calls[ref.sha256] += 1
        return AssetCard(sha256=ref.sha256, kind=ref.kind, summary=ref.sha256)

    monkeypatch.setattr(analyse, "analyse_image", analyse_image)
    monkeypatch.setattr(analyse, "load_cached", lambda *args: None)
    monkeypatch.setattr(analyse, "save_cached", lambda ref, *args: saved.append(ref.sha256))
    backend = SimpleNamespace(cfg=SimpleNamespace(model="test"))
    cards = analyse.analyse_all(backend, [make_ref("b"), make_ref("a"), make_ref("b")])
    assert list(cards) == ["b", "a"]
    assert calls == {"a": 1, "b": 1}
    assert saved == ["b", "a"]


def test_worker_failure_logs_and_preserves_asset_context(monkeypatch, caplog):
    def analyse_image(backend, ref, **kwargs):
        raise analyse.AssetAnalysisError("decode failed with visible detail")

    monkeypatch.setattr(analyse, "analyse_image", analyse_image)
    ref = make_ref("broken")
    ref.path = "/tmp/broken-asset.png"
    backend = SimpleNamespace(cfg=SimpleNamespace(model="test"))
    with pytest.raises(analyse.AssetAnalysisError, match="broken-asset.png"):
        analyse.analyse_all(backend, [ref], use_cache=False)
    assert "decode failed with visible detail" in caplog.text
    assert "broken" in caplog.text
