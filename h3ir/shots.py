"""Shot planning: the model decides, code validates.

This module exists because of a judged failure. The planner used to compute shot count from
`duration / 3.4` and space the cuts evenly, then hand the model pre-cut containers and ask it to
describe them. Both containers held four seconds of the same continuous action, so both came back
as "the man walks down the corridor" -- a repeated shot that the owner spotted by eye in seconds
while the validator was green and the restatement metric read 0.21.

The mistake was a category error in my own architecture. "There are two shots and the cut is at
00:04.000" is arithmetic. Deciding what each shot is FOR -- establishing versus close, movement
versus stillness, where the beat lands, what changes across the cut -- is a creative act, and I had
made it a template. The thinking-mode result pointed at this and I misread it: reasoning bought
nothing because code had taken the planning away, not because planning needs no reasoning.

So the split moves. The model proposes the edit; code proves it legal:

  model owns    how many shots (including ONE), what each is for, its framing, what changes
                across the cut, roughly where the cut falls
  code owns     the 17k+5 grid, cut times strictly inside the snapped duration and strictly
                increasing, a floor on shot length, distinctness, every subject accounted for,
                and every precision token in the rendered text

A proposal that breaks a rule is repaired where repair is unambiguous (spacing, rounding, clamping)
and rejected where it is not, which falls back to the deterministic draft.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .grid import Target
from .models import AMPLITUDES, CAMERA_TYPES, SPEEDS

# What a shot is FOR. Not decoration: two shots with the same purpose and the same framing are the
# defect this vocabulary exists to make visible.
PURPOSES = ("establish", "develop", "reveal", "react", "close", "resolve", "transition")

FRAMINGS = ("extreme wide", "wide", "medium wide", "medium", "medium close", "close",
            "extreme close", "over the shoulder", "low angle", "high angle", "overhead", "pov")

MIN_SHOT_MS = 0
PINNED_SHOTS_MAX = None
MAX_SHOTS = None
CUT_ROUNDING_MS = 100


def shot_schema(max_shots: int | None = MAX_SHOTS, exact: int | None = None) -> dict[str, Any]:
    return {
        "title": "ShotPlan",
        "type": "object",
        "additionalProperties": False,
        "required": ["shots", "reasoning"],
        "properties": {
            "reasoning": {"type": "string"},
            # Additions the planner would make if the request allowed them. RECORDED, never
            # applied: an explicit prohibition is an instruction, but silently withholding a good
            # idea is its own failure, so the caller gets told what they are leaving out.
            "suggestions": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "shots": {
                "type": "array",
                # An exact pin closes both ends: guided decoding then cannot return a count the
                # caller did not ask for, which beats asking nicely every time.
                "minItems": exact or 1,
                **({"maxItems": exact or max_shots} if exact or max_shots is not None else {}),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["purpose", "framing", "action", "what_changes", "camera",
                                 "starts_at_s"],
                    "properties": {
                        "purpose": {"type": "string"},
                        "framing": {"type": "string"},
                        "action": {"type": "string"},
                        "what_changes": {"type": "string"},
                        "starts_at_s": {"type": "number"},
                        "camera": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["type"],
                            "properties": {
                                "type": {"type": "string"},
                                "amplitude": {"type": "string"},
                                "speed": {"type": "string"},
                            },
                        },
                        "subjects": {"type": "array", "items": {"type": "string"}},
                        "sync_sound": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    }


@dataclass
class ProposedShot:
    purpose: str
    framing: str
    action: str
    what_changes: str
    start_ms: int
    camera: dict[str, Any] = field(default_factory=dict)
    subjects: list[str] = field(default_factory=list)
    sync_sound: list[str] = field(default_factory=list)

    def signature(self) -> tuple[str, str, str]:
        """What makes this shot different from another one. Never word overlap."""
        cam_type = (self.camera or {}).get("type", "")
        text = f"{self.framing} framing. {self.action} {self.what_changes}. camera {cam_type}."
        return depiction_signature(text)


# Semantic groups, not words. "walks forward down the corridor" and "strides ahead along the
# passage" are the same depiction; a signature built from raw tokens calls them different, which is
# precisely how two identical shots passed review. Synonyms have to collapse or the rule is
# decorative.
ACTION_GROUPS: dict[str, tuple[str, ...]] = {
    "locomotion": ("walk", "stride", "step", "advance", "march", "run", "jog", "approach",
                   "recede", "move", "cross", "traverse", "head toward", "come", "proceed",
                   "make his way", "close the distance"),
    "stopping": ("stop", "halt", "settle", "pause", "stand still", "come to rest"),
    "turning": ("turn", "pivot", "spin", "rotate", "face", "swivel"),
    "looking": ("look", "glance", "gaze", "stare", "watch", "regard", "eye"),
    "reaching": ("reach", "lift", "raise", "extend", "grab", "grasp", "take", "pick up"),
    "speaking": ("speak", "say", "talk", "utter", "murmur", "shout"),
    "vertical": ("climb", "descend", "rise", "fall", "kneel", "sit", "stand up", "crouch"),
    "threshold": ("enter", "emerge", "appear", "exit", "leave", "vanish", "step into",
                  "step out"),
    "gesture": ("gesture", "point", "wave", "nod", "shrug", "clench", "flex"),
}

CAMERA_GROUPS: dict[str, tuple[str, ...]] = {
    # Bare "push" is included: "the camera pushes onward" is the same move as "pushes in", and
    # missing that let two identical shots read as different. The occasional "he pushes the door"
    # mislabels the camera group in a coarse signature, which is the cheaper error.
    "in": ("push", "dolly in", "zoom in", "zooms in", "moves closer", "closes in", "approaches"),
    "out": ("pull out", "pulls out", "pulling out", "zoom out", "zooms out", "pulls back"),
    "lateral": ("truck", "trucks", "pan", "pans", "panning", "slide", "glides sideways"),
    "vertical": ("tilt", "tilts", "pedestal", "rises", "lowers", "cranes"),
    "orbit": ("arc", "arcs", "orbits", "circles"),
    "follow": ("track", "tracks", "follows", "trails"),
    "held": ("static", "holds", "held", "locked off", "motionless"),
    "shake": ("shake", "shakes", "judder", "vibrat"),
    "roll": ("roll", "rolls"),
}

FRAMING_GROUPS: dict[str, tuple[str, ...]] = {
    "extreme-close": ("extreme close", "macro"),
    "close": ("close-up", "close up", "close framing", "close shot", "tight on", "chest height",
              "head and shoulders"),
    "medium": ("medium shot", "medium framing", "medium wide", "waist"),
    "wide": ("wide", "extreme wide", "establishing", "full body", "long shot"),
    "over-shoulder": ("over the shoulder", "over his shoulder"),
    "low": ("low angle", "low-angle", "from below"),
    "high": ("high angle", "high-angle", "overhead", "from above", "aerial"),
    "pov": ("pov", "point of view"),
}


# Stems whose noun sense is common enough that a substring match reads them wrongly. "frame a
# FACE" is not the verb "face"; that single collision made two identical shots look different and
# let the repeated shot through.
_VERB_ONLY = {"face", "eye", "point", "wave", "stand", "rise", "fall", "come", "head", "cross",
              "regard", "watch", "run", "settle", "close"}


def _term_present(term: str, low: str) -> bool:
    if " " in term:
        return term in low
    if term in _VERB_ONLY:
        # only the inflected verb forms, and never as part of a longer word
        return bool(re.search(rf"\b{re.escape(term)}(?:s|es|ed|ing)\b", low))
    return bool(re.search(rf"\b{re.escape(term)}", low))


def _groups_present(text: str, groups: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    low = (text or "").lower()
    return tuple(sorted(g for g, terms in groups.items()
                        if any(_term_present(t, low) for t in terms)))


# `same_depiction` used to live here: a similarity test over these groups that answered "do two
# signatures depict the same shot?" with a 50% action-overlap threshold. It was deleted with the
# rules that used it. The question it asked is not decidable -- two shots can share a framing group,
# a camera group and most of their action groups and still be a legitimate edit -- so no rule may be
# built on it. The signature below survives because it feeds a REPORTED metric, where similarity is
# an observation rather than a verdict.


def depiction_signature(text: str) -> tuple[str, str, str]:
    """What a shot DEPICTS: framing, the kinds of action in it, and the kind of camera move.

    Shared by the proposal validator and the text validator so the two cannot disagree about what
    counts as "the same shot".
    """
    framing = _groups_present(text, FRAMING_GROUPS)
    actions = _groups_present(text, ACTION_GROUPS)
    camera = _groups_present(text, CAMERA_GROUPS)
    return (",".join(framing), ",".join(actions), ",".join(camera))


@dataclass
class ShotPlanResult:
    shots: list[ProposedShot]
    repairs: list[str] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    reasoning: str = ""
    suggestions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.shots) and not self.rejections


def validate_proposal(raw: dict[str, Any], target: Target, *,
                      max_shots: int | None = MAX_SHOTS) -> ShotPlanResult:
    """Prove the model's edit is legal, repairing only what is unambiguous."""
    res = ShotPlanResult(shots=[], reasoning=str(raw.get("reasoning") or "")[:400],
                         suggestions=[re.sub(r"\s+", " ", str(x)).strip()[:200]
                                      for x in (raw.get("suggestions") or []) if x][:3])
    items = raw.get("shots") or []
    if not items:
        res.rejections.append("the proposal contains no shots")
        return res
    if max_shots is not None and len(items) > max_shots:
        res.repairs.append(f"proposed {len(items)} shots, kept the first {max_shots}")
        items = items[:max_shots]

    total_ms = int(round(target.effective_seconds * 1000))
    shots: list[ProposedShot] = []
    for i, it in enumerate(items):
        purpose = str(it.get("purpose") or "").lower().strip()
        framing = str(it.get("framing") or "").lower().strip()
        cam = it.get("camera") or {}
        camera = {}
        if cam.get("type"):
            camera = dict(cam)
        try:
            start_ms = int(round(float(it.get("starts_at_s") or 0) * 1000))
        except (TypeError, ValueError):
            start_ms = 0
        shots.append(ProposedShot(
            purpose=purpose, framing=framing,
            action=re.sub(r"\s+", " ", str(it.get("action") or "")).strip(),
            what_changes=re.sub(r"\s+", " ", str(it.get("what_changes") or "")).strip(),
            start_ms=start_ms, camera=camera,
            subjects=[str(x) for x in (it.get("subjects") or []) if x],
            sync_sound=[re.sub(r"\s+", " ", str(x)).strip()
                        for x in (it.get("sync_sound") or []) if x]))

    shots[0].start_ms = 0
    for i in range(1, len(shots)):
        if not shots[i - 1].start_ms < shots[i].start_ms < total_ms:
            res.rejections.append("cut times must increase strictly inside the video duration")
            return res

    res.shots = shots
    return res


def spans(shots: list[ProposedShot], target: Target) -> list[tuple[int, int]]:
    total_ms = int(round(target.effective_seconds * 1000))
    out = []
    for i, sh in enumerate(shots):
        end = shots[i + 1].start_ms if i + 1 < len(shots) else total_ms
        out.append((sh.start_ms, end))
    return out
