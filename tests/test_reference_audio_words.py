"""The words on an attached recording, and the one stage that was never given them.

ref-en.txt 5.4: "When dialogue, narration, or lyrics from reference audio are directly reused, or
when the input prompt explicitly requests their reperformance, preserve the exact source words and
original language inside `<d>`."

Measured 0 of 7 on a request that asks for exactly that ("Have the man at the counter say again,
word for word, the line that is on the recording"), with the words supplied through the documented
channel (`transcripts: {sha: "We close at six, not half past."}`). Every one of the seven
acknowledged the obligation in `retention_analysis` and none discharged it: no `<d>` block anywhere.

The transcript reached `analyse_audio` and then `plan_shots` and `beat_sheet`, and stopped there.
`compose_brief` writes every section that ships and builds its facts from the subject definition
lines, which walk `subjects` and never touch `cards[...].transcript` -- so for an audio-only brief
the writer fell into the `unnamed` branch and was told, in as many words, "you have NOT heard it and
cannot describe what it contains. Say only what its note above states."

The other half of 5.4 is a prohibition, and it has to survive the fix: "When only timbre, rhythm,
emotion, or delivery is referenced, do not carry the original dialogue from the reference audio into
the target video." So the words are handed over with both branches attached, and the validator
enforces only what it can decide.
"""
from __future__ import annotations

from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode, Role
from h3ir.plan import ProfileOptions
from h3ir.validate import Context, validate

WORDS = "We close at six, not half past."


def _doc(desc: str, *, marker: str = "reference") -> str:
    return ("subject_definitions:\n"
            "<Audio 1> is the voice-timbre reference for the speaker (S1), containing a spoken "
            "vocal layer.\n<Subject 1> is the man at the counter, with a grey apron.\n\n"
            "summary:\n[reference generation + audio reference] The target video shows "
            "<Subject 1> repeating the line on <Audio 1>.\n\n"
            "retention_analysis:\n"
            "<Subject 1> (appears in [Shot 1]): fully_preserved - the grey apron is retained.\n"
            f"<Audio 1>: {marker} - the target speaker follows <Audio 1>.\n\n"
            f"detailed_description:\nThe target video is in cinematic style.\n[Shot 1] {desc}\n\n"
            "overall_soundscape:\nA fridge hums behind the counter.\n\n"
            "non_diegetic_music:\nN/A\n")


def _ctx(**kw) -> Context:
    base = dict(mode="ref2va", n_pictures=0, n_audios=1, duration_s=8.0,
                audio_transcripts=(("<Audio 1>", WORDS),))
    base.update(kw)
    return Context(**base)


SAYS = ("The camera pushes in with small amplitude at slow speed as <Subject 1> (S1) repeats the "
        "line word for word: ")


# ---------------------------------------------------------------- the words reach the document

def test_the_words_inside_a_d_block_satisfy_everything():
    found = validate(_doc(SAYS + f"<d>[English] {WORDS}</d>"), _ctx())
    # P2-too-short is expected: these fixtures are a few sentences, not a 400-word brief.
    assert not [f for f in found if f.rule != "P2-too-short"], [str(f) for f in found]










def test_no_transcript_means_no_finding():
    found = validate(_doc("The camera holds a static shot on <Subject 1>."),
                     _ctx(audio_transcripts=()))
    assert not [f for f in found if f.rule.startswith("D1")], [str(f) for f in found]


def test_one_sentence_of_a_longer_transcript_is_enough():
    """The words are the caller's and the writer may quote the part the request asks for; demanding
    the whole transcript would fire on a legitimate partial reperformance."""
    long = "Hold the line. We close at six, not half past. Come back tomorrow."
    found = validate(_doc(SAYS + f"<d>[English] {WORDS}</d>"),
                     _ctx(audio_transcripts=(("<Audio 1>", long),)))
    assert not [f for f in found if f.rule != "P2-too-short"], [str(f) for f in found]


# ---------------------------------------------------------------- the writer is given the words

def _capture_ask(role: Role, transcript: str, intent: str) -> str:
    """One real compose call with the model replaced. The transcript travels the same way the
    service sends it: through `compile_brief(transcripts=...)` into the card."""
    from h3ir.analyse import analyse_audio
    from h3ir.draft import deterministic_draft
    from h3ir.prose import compose_brief

    class Capture:
        class _Cfg:
            model = "capture"
        cfg = _Cfg()

        class _Reply:
            content = "subject_definitions:\n"

        def __init__(self) -> None:
            self.asks: list[str] = []

        def chat(self, messages, **kw):
            c = messages[-1]["content"]
            self.asks.append(c if isinstance(c, str) else c[0]["text"])
            return self._Reply()

    ref = AssetRef(kind=AssetKind.AUDIO, role=role, sha256="wav", seconds=3.0,
                   note="a flat male voice, close mic")
    card = analyse_audio(ref, transcript)
    brief = Brief(intent=intent, seconds=8.0, assets=[ref])
    plan = deterministic_draft(brief, Mode.REF2VA, {"wav": card}, opts=ProfileOptions())
    backend = Capture()
    compose_brief(backend, brief, plan.subjects, {"wav": card}, plan.target,
                  tuple(m.label for m in plan.manifest), prompt_name="compose.v2.txt",
                  mode=Mode.REF2VA, task_types=tuple(plan.task_types),
                  audio_transcripts=tuple((m.label, card.transcript)
                                          for m in plan.manifest if m.label.startswith("<Audio")))
    return backend.asks[0]


def test_the_ask_carries_the_transcribed_words_verbatim():
    ask = _capture_ask(Role.VOICE_TIMBRE, WORDS,
                       "Have the man at the counter say again, word for word, the line that is "
                       "on the recording.")
    assert WORDS in ask, ask
    assert "<Audio 1>" in ask


def test_the_ask_preserves_audio_role_and_transcript_facts():
    import json
    ask = _capture_ask(Role.VOICE_TIMBRE, WORDS, "Reuse this voice for the man at the counter.")
    facts = json.loads(ask.split("\n\n", 1)[1])
    assert facts["asset_requests"][0]["role"] == "voice_timbre"
    assert facts["audio_transcripts"] == [["<Audio 1>", WORDS]]


def test_the_ask_preserves_the_request_to_reperform_audio():
    import json
    intent = "Have the man at the counter say the line on the recording again."
    facts = json.loads(_capture_ask(Role.VOICE_TIMBRE, WORDS, intent).split("\n\n", 1)[1])
    assert facts["request"] == intent
    assert facts["audio_transcripts"] == [["<Audio 1>", WORDS]]


def test_the_ask_says_nothing_about_words_when_no_transcript_was_supplied():
    ask = _capture_ask(Role.BGM, "", "Score this like the attached track.")
    assert "transcrib" not in ask.lower(), ask


def test_the_compiler_passes_the_transcript_to_the_composer(monkeypatch):
    """A test on the plumbing rather than on the helper: the fact is only worth anything if the real
    compile hands it over. This is the line that was missing."""
    import pytest

    import h3ir.compile as C
    from h3ir.analyse import analyse_audio
    from h3ir.models import ModeDecision

    ref = AssetRef(kind=AssetKind.AUDIO, role=Role.VOICE_TIMBRE, sha256="wav", seconds=3.0,
                   note="a flat male voice")
    cards = {"wav": analyse_audio(ref, WORDS)}
    seen: dict[str, object] = {}

    def spy(backend, brief, subjects, cards_, target, labels, **kw):
        seen.update(kw)
        raise RuntimeError("stop here; the ask is what this test is about")

    class _Backend:
        class cfg:
            model = "capture"

        def require_available(self): pass
        def server_version(self): return "test"
        def close(self): pass

    monkeypatch.setattr(C, "compose_brief", spy)
    monkeypatch.setattr(C, "analyse_all", lambda *a, **k: cards)
    monkeypatch.setattr(C, "infer_mode", lambda *a, **k: ModeDecision(
        mode=Mode.REF2VA, confidence=1.0, rule_fired="audio-attached", signals=[]))
    brief = Brief(intent="Have the man say the line on the recording again, word for word.",
                  seconds=8.0, assets=[ref])
    with pytest.raises(RuntimeError):
        C.compile_brief(brief, backend=_Backend(), opts=ProfileOptions(),
                        transcripts={"wav": WORDS})
    assert seen["audio_transcripts"] == (("<Audio 1>", WORDS),)


def test_the_validator_context_carries_it_on_both_paths():
    """`_assess` (the draft) and `_written_context` (the model's brief) must agree, or the rule would
    exist on one path only."""
    from h3ir.analyse import analyse_audio
    from h3ir.compile import _written_context
    from h3ir.draft import deterministic_draft

    ref = AssetRef(kind=AssetKind.AUDIO, role=Role.VOICE_TIMBRE, sha256="wav", seconds=3.0,
                   note="a flat male voice")
    cards = {"wav": analyse_audio(ref, WORDS)}
    brief = Brief(intent="say it again word for word", seconds=8.0, assets=[ref])
    plan = deterministic_draft(brief, Mode.REF2VA, cards, opts=ProfileOptions())
    ctx = _written_context(brief, Mode.REF2VA, plan, cards, 500, None)
    assert ctx.audio_transcripts == (("<Audio 1>", WORDS),)
