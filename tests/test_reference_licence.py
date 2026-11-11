"""What a reference plate does and does not licence the compiler to assert.

The rule: **appearance is identity, pose is a property of the photograph.** A character sheet
shows a combat stance; a request that has the character walking down a corridor owns the action.
The one exception is principled rather than convenient — when the plate IS a frame of the video
(a frame anchor), its pose is the video's pose and does carry forward.

This is the same grounded/ungrounded discipline the labels use, applied to attribute classes.
Every test here corresponds to something that reached a real artifact.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from h3ir.draft import deterministic_draft
from h3ir.licence import resolve_licence
from h3ir.style import (StyleDecision, _tidy, classify_medium,
                        resolve_style, style_terms_in)
from h3ir.models import AssetCard, AssetKind, AssetRef, Brief, Mode, Role, SubjectPlan
from h3ir.plan import ProfileOptions, build_manifest, build_subjects
from h3ir.render import render_ir, render_retention, render_subject_definitions, style_sentence
from h3ir.validate import Context, validate

POSE = ["fists clenched in a fighting stance", "looking toward the camera"]
IDENTITY = ["black hair shaved at the sides", "a thin pale scar through the left eyebrow",
            "charcoal technical jacket", "worn black boots"]


def _character_card() -> AssetCard:
    return AssetCard(sha256="char", kind=AssetKind.IMAGE, style="Anime",
                     subjects=[{"kind": "person", "descriptor": "the man",
                                "attributes": list(IDENTITY), "pose": list(POSE)}])


def _corridor_card() -> AssetCard:
    return AssetCard(
        sha256="corr", kind=AssetKind.IMAGE, environment="Interior of a stone corridor",
        lighting="warm torchlight",
        subjects=[{"kind": "object", "descriptor": "the wall torch",
                   "attributes": ["metal cage holder", "orange flame"], "pose": []},
                  {"kind": "object", "descriptor": "the stone wall",
                   "attributes": ["irregular blocks", "mortar lines"], "pose": []},
                  {"kind": "object", "descriptor": "the vines",
                   "attributes": ["green leaves"], "pose": []}])


def _brief(role=Role.SUBJECT, intent="the man walks forward down the stone corridor") -> Brief:
    return Brief(intent=intent, seconds=8, canvas=(1056, 608),
                 assets=[AssetRef(kind=AssetKind.IMAGE, role=role, sha256="char", px=(443, 768))])


def _plan(role=Role.SUBJECT, cards=None, brief=None):
    b = brief or _brief(role)
    return deterministic_draft(b, Mode.REF2VA, cards or {"char": _character_card()},
                               opts=ProfileOptions())


# ---------------------------------------------------------------- pose is not identity

def test_a_subject_plate_does_not_put_its_pose_in_the_definition():
    out = render_subject_definitions(_plan())
    assert "black hair shaved at the sides" in out, "identity must carry forward"
    assert "fighting stance" not in out, "the plate's pose is not who the subject is"
    assert "toward the camera" not in out


def test_a_subject_plate_does_not_put_its_pose_in_the_retention_contract():
    out = render_retention(_plan())
    assert "fully_preserved" in out
    assert "stance" not in out and "toward the camera" not in out


def test_a_frame_anchor_DOES_licence_its_pose():
    """The exception, and the reason it is principled: when the plate is frame 0 of the video,
    its pose IS the video's opening pose. Suppressing it there would lose real information."""
    plan = _plan(role=Role.FRAME_ANCHOR_FIRST)
    subj = plan.subjects[0]
    assert subj.pose_licensed is True
    out = render_subject_definitions(plan)
    assert "fighting stance" in out


def test_the_pose_is_still_recorded_even_when_not_asserted():
    """We do not discard it — it is handed to the prose stage precisely so the stage can be told
    to exclude it, and it matters if the same plate is later reused as an anchor."""
    subj = _plan().subjects[0]
    assert subj.pose == POSE
    assert subj.pose_licensed is False




def test_the_same_words_are_legal_in_the_description():
    """The description is where actions belong. A rule that fired there would forbid the request
    itself, since the request is what asks the man to clench his fists."""
    text = ("subject_definitions:\n<Subject 1> is the man in <Picture 1>, with dark hair.\n\n"
            "summary:\n[reference generation] The target video shows <Subject 1>.\n\n"
            "retention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - "
            "the hair is retained.\n\ndetailed_description:\nA style line.\n"
            "[Shot 1] <Subject 1> advances with fists clenched in a fighting stance as the "
            "camera holds a static shot.\n\noverall_soundscape:\nWind.\n\n"
            "non_diegetic_music:\nN/A\n")
    rules = {f.rule for f in validate(text, Context(n_pictures=1)) if f.severity == "WARN"}
    assert "R12-pose-as-identity" not in rules


def test_a_licensed_pose_is_not_flagged():
    text = ("subject_definitions:\n<Subject 1> is the man in <Picture 1>, with dark hair, "
            "fists clenched in a fighting stance.\n\nsummary:\n"
            "[keyframe completion] The target video opens on <Subject 1>.\n\n"
            "retention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - "
            "the hair is retained.\n\ndetailed_description:\nA style line.\n"
            "[Shot 1] The camera holds a static shot on <Subject 1>.\n\n"
            "overall_soundscape:\nWind.\n\nnon_diegetic_music:\nN/A\n")
    rules = {f.rule for f in validate(text, Context(n_pictures=1, pose_licensed=True))
             if f.severity == "WARN"}
    assert "R12-pose-as-identity" not in rules


# ---------------------------------------------------------------- environment is one place

def test_an_environment_plate_yields_one_subject_not_an_inventory():
    """Three subjects from one corridor plate spent the word budget re-listing wall textures and
    made every shot restate the same furniture."""
    brief = Brief(intent="a man walks down a corridor", seconds=8,
                  assets=[AssetRef(kind=AssetKind.IMAGE, role=Role.ENVIRONMENT, sha256="corr",
                                   px=(403, 552))])
    manifest = build_manifest(brief, __import__("h3ir.grid", fromlist=["Target"]).Target.build(8))
    subjects = build_subjects(manifest, {"corr": _corridor_card()})
    assert len(subjects) == 1, [s.descriptor for s in subjects]
    only = subjects[0]
    assert only.kind == "environment"
    assert only.descriptor.startswith(("a ", "an ", "the ")), only.descriptor
    joined = " ".join(only.attributes)
    assert "torch" in joined and "wall" in joined, "the parts survive as features of the place"


def test_a_subject_plate_still_yields_its_subjects():
    brief = _brief()
    manifest = build_manifest(brief, __import__("h3ir.grid", fromlist=["Target"]).Target.build(8))
    assert len(build_subjects(manifest, {"char": _character_card()})) == 1


# ---------------------------------------------------------------- the draft must not override style

def test_the_draft_falls_back_to_the_card_when_no_style_was_asked_for():
    brief = _brief(intent="the man walks down the corridor")
    card = AssetCard(sha256="char", kind=AssetKind.IMAGE, style="a claymation look",
                     subjects=[{"kind": "person", "descriptor": "the man",
                                "attributes": list(IDENTITY), "pose": []}])
    plan = deterministic_draft(brief, Mode.REF2VA, {"char": card}, opts=ProfileOptions())
    assert "claymation" in plan.style_phrase.lower()


@pytest.mark.parametrize("raw,want", [
    ("resembling a video game cutscene", "video game cutscene"),
    ("a realistic 3D style", "realistic 3D"),
    ("Interior of a stone structure.", "Interior of a stone structure"),
])
def test_card_prose_is_tidied_into_a_noun_phrase(raw, want):
    """These produced 'style with resembling a video game cutscene'."""
    assert _tidy(raw) == want


def test_requested_style_terms_keep_the_callers_order():
    assert style_terms_in("Anime style, cinematic, moody")[:2] == ["anime", "cinematic"]
    assert style_terms_in("a man walks") == []


# ------------------------------------------------- the style-conflict decision, stated explicitly

def _card_with_style(style: str) -> AssetCard:
    return AssetCard(sha256="char", kind=AssetKind.IMAGE, style=style,
                     subjects=[{"kind": "person", "descriptor": "the man",
                                "attributes": list(IDENTITY), "pose": list(POSE)}])








def test_a_transformation_does_NOT_touch_the_retention_marker():
    """**Reversed, against the spec's own words.** This test used to assert the opposite.

    `ref-en.txt` §4.1 defines `attribute_transfer` as *"Referenced characteristics are transferred to
    a different identifiable target subject"* — it is about the target being a DIFFERENT SUBJECT, not
    about the rendering changing. "Reimagine the man as anime" keeps the same identifiable target
    subject, so the marker does not apply, and asserting it made the compiler state something the
    format defines as something else.

    The medium travels through the style opening of `detailed_description`, which is where the spec
    puts it and where the writer already puts it. See §43.
    """
    cards = {"char": _card_with_style("stylised comic illustration")}
    plan = deterministic_draft(_brief(intent="reimagine the man as anime while he walks"),
                               Mode.REF2VA, cards, opts=ProfileOptions())
    assert "attribute_transfer" not in render_retention(plan)
    assert "fully_preserved" in render_retention(plan)




def test_naming_a_garment_takes_the_wardrobe():
    from h3ir.licence import WARDROBE
    cards = {"char": _card_with_style("stylised comic illustration")}
    lic = resolve_licence(_brief(intent="the man walks, now wearing a red jacket"), cards)
    assert lic.governs[WARDROBE] == "request"


def test_with_no_visual_reference_the_request_governs_everything():
    from h3ir.licence import ATTRIBUTES
    lic = resolve_licence(Brief(intent="a man walks down a corridor, anime style"), {})
    assert all(lic.governs[a] == "request" for a in ATTRIBUTES)


def test_saying_nothing_about_style_uses_the_observation():
    d = resolve_style(_brief(intent="the man walks down the corridor"),
                      {"char": _card_with_style("3D computer animation")})
    assert d.source == "reference"
    assert "3D computer animation" in d.phrase


def test_a_treatment_word_is_not_a_medium_conflict():
    d = resolve_style(_brief(intent="the man walks, cinematic and moody"),
                      {"char": _card_with_style("3D computer animation")})
    assert d.discrepancy is False


@pytest.mark.parametrize("text,bucket", [
    ("Anime style", "2d-animation"),
    ("realistic 3D computer animation resembling a video game cutscene", "3d-animation"),
    ("shot on 16mm, black and white film", "archival"),
    ("claymation puppets", "stop-motion"),
    ("watercolour storybook", "painted"),
    ("photorealistic live-action", "live-action"),
    ("a man walks forward", None),
])
def test_medium_classification(text, bucket):
    assert classify_medium(text) == bucket


def test_the_draft_renders_no_grammar_seams():
    brief = _brief(intent="the man walks down the corridor. Anime style, cinematic.")
    plan = deterministic_draft(brief, Mode.REF2VA, {"char": _character_card(),
                                                   "corr": _corridor_card()},
                               opts=ProfileOptions())
    out = render_ir(plan, ProfileOptions()).prompt
    assert "style style" not in out
    assert "with resembling" not in out
    assert ".." not in out
    body = out.split("[Shot 1]", 1)[1] if "[Shot 1]" in out else out
    assert "is Interior" not in body, "a spliced clause must not capitalise mid-sentence"


def test_style_sentence_never_doubles_the_word():
    assert "style style" not in style_sentence("Anime style, cinematic")


def test_the_card_cache_key_changes_when_the_card_contract_changes():
    """A v1 card folds pose into attributes. Reusing one silently reintroduces the very
    contamination the split prevents, so the analyzer version is part of the cache key and must
    move whenever the card's shape does."""
    from h3ir.analyse import ANALYZER_VERSION, _cache_key
    from h3ir.models import AssetKind, AssetRef, Role

    ref = AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256="abc")
    assert int(ANALYZER_VERSION) >= 2, "the identity/pose split is version 2 of the contract"
    key_now = _cache_key(ref, "some-model")
    import h3ir.analyse as an
    old = an.ANALYZER_VERSION
    try:
        an.ANALYZER_VERSION = "1"
        assert _cache_key(ref, "some-model") != key_now
    finally:
        an.ANALYZER_VERSION = old


# ------------------------------------------------- reference-sheet hygiene

SHEET_BRIEF = ("subject_definitions:\n<Subject 1> is the man in <Picture 1>, with a navy "
               "t-shirt.\n\nsummary:\n[reference generation] The target video shows "
               "<Subject 1>.\n\nretention_analysis:\n<Subject 1> (appears in [Shot 1]): "
               "fully_preserved - the navy t-shirt is retained.\n\ndetailed_description:\n"
               "A style line.\n[Shot 1] {body}\n\noverall_soundscape:\nWind.\n\n"
               "non_diegetic_music:\nN/A\n")




@pytest.mark.parametrize("body", [
    "<Subject 1> glances back down the corridor as the light shifts.",
    "The background walls blur as <Subject 1> walks toward the front of the frame.",
    "<Subject 1> turns his back to the camera and walks away.",
])
def test_ordinary_words_are_not_sheet_labels(body):
    """The labels are printed in capitals; 'back' and 'front' are ordinary words. A rule that
    fired on 'he looks back' would reject innocent prose."""
    from h3ir.validate import Context, validate
    text = SHEET_BRIEF.format(body=body)
    rules = {f.rule for f in validate(text, Context(n_pictures=1, has_reference_sheet=True))
             if f.severity == "WARN"}
    assert "R13-sheet-artefact" not in rules, body


def test_a_turnaround_yields_one_subject_not_eight():
    """Eight views of one man is one man. Decomposing a multi-panel sheet the way the corridor was
    decomposed would define the same person eight times."""
    from h3ir.grid import Target
    from h3ir.plan import build_manifest, build_subjects
    views = [{"kind": "person", "descriptor": f"the man ({v})",
              "attributes": ["navy t-shirt", "dark blue jeans", f"seen from {v}"], "pose": []}
             for v in ("front", "left", "right", "back", "left 3/4", "right 3/4", "relaxed",
                       "casual")]
    card = AssetCard(sha256="sheet", kind=AssetKind.IMAGE, style="digital illustration",
                     subjects=views, is_reference_sheet=True)
    brief = Brief(intent="the man walks", seconds=8,
                  assets=[AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256="sheet",
                                   px=(1448, 1086))])
    subjects = build_subjects(build_manifest(brief, Target.build(8)), {"sheet": card})
    assert len(subjects) == 1, [s.descriptor for s in subjects]
    joined = " ".join(subjects[0].attributes).lower()
    assert "navy t-shirt" in joined and "jeans" in joined, "the views merge into one description"
    assert subjects[0].pose == [], "a sheet's poses are the sheet's"


def test_a_sheets_studio_lighting_does_not_become_the_videos():
    """A sheet is lit for legibility. Carrying that over put "even, diffuse studio lighting with
    soft shadows cast on the floor" into a torchlit corridor."""
    from h3ir.style import observed_style
    sheet = AssetCard(sha256="s", kind=AssetKind.IMAGE, style="digital illustration",
                      lighting="Even, diffuse studio lighting with soft shadows on the floor",
                      is_reference_sheet=True)
    assert observed_style({"s": sheet}) == "digital illustration"
    scene = AssetCard(sha256="s", kind=AssetKind.IMAGE, style="live-action",
                      lighting="Warm torchlight", is_reference_sheet=False)
    assert "torchlight" in observed_style({"s": scene})




# ------------------------------------------------- the style opening, as one rule

@pytest.mark.parametrize("phrase,must_not", [
    ("Anime style, cinematic", "style style"),
    ("Anime, cinematic", "with cinematic."),
    ("digital illustration, semi-realistic character design", "with resembling"),
])
def test_the_style_opening_is_grammatical(phrase, must_not):
    """Three separate grammar bugs came out of this one sentence, so the shape of the join is
    derived from the remainder rather than fixed."""
    from h3ir.render import style_sentence
    out = style_sentence(phrase)
    assert must_not not in out, out
    assert out.endswith("."), out
    assert "  " not in out


def test_a_treatment_only_remainder_takes_a_comma_not_with():
    from h3ir.render import style_sentence
    assert style_sentence("Anime, cinematic") == "The target video is in anime style, cinematic."


def test_a_noun_remainder_still_takes_with():
    from h3ir.render import style_sentence
    out = style_sentence("digital illustration, semi-realistic character design")
    assert out == ("The target video is in digital illustration style with "
                   "semi-realistic character design.")




def test_a_well_formed_opening_passes():
    from h3ir.validate import Context, validate
    good = "The target video is in digital illustration style with warm directional lighting."
    text = ("subject_definitions:\n<Subject 1> is the man in <Picture 1>, with dark hair.\n\n"
            "summary:\n[reference generation] The target video shows <Subject 1>.\n\n"
            "retention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - "
            "the hair is retained.\n\ndetailed_description:\n" + good + "\n"
            "[Shot 1] <Subject 1> walks forward.\n\noverall_soundscape:\nWind.\n\n"
            "non_diegetic_music:\nN/A\n")
    rules = {f.rule for f in validate(text, Context(n_pictures=1)) if f.severity == "ERROR"}
    assert "R16-style-opening-malformed" not in rules








# ---------------------------------------------------------------------------
# Two defects found by running the shipping path against the live endpoint,
# after the suite was green. Both live in how a transformation is DETECTED and
# then REPORTED, and both were silent.
# ---------------------------------------------------------------------------

INFLECTED_TRANSFORMS = (
    "the man walks down the corridor, reimagined as anime",
    "reimagined as a 1990s cel animation",
    "restyled as claymation",
    "redrawn as a woodcut print",
    "converted to black and white film",
    "transformed into an oil painting",
)


@pytest.mark.parametrize("intent", INFLECTED_TRANSFORMS)
def test_an_inflected_transforming_verb_is_still_a_transformation(intent):
    """The owner named this exception himself -- "unless the prompt states it like 'reimagine as'".

    The verb alternation was written in the bare infinitive, and `\\breimagine\\b` cannot match the
    `d` in "reimagined", so every past-participle phrasing -- which is the NATURAL way to write it
    -- fell through to preservation with no finding at all. A silent wrong answer: the caller asked
    for a departure and got the reference's style back, and nothing said so.
    """
    from h3ir.licence import transformation_intent
    assert transformation_intent(Brief(intent=intent)) is not None, intent


@pytest.mark.parametrize("intent,expect", [
    ("reimagined as a 1990s cel animation", "1990s cel animation"),
    ("restyled as claymation", "claymation"),
    ("redrawn as a woodcut print", "woodcut print"),
    ("transformed into an oil painting", "oil painting"),
])
def test_an_inflected_transformation_still_names_its_target(intent, expect):
    """Detecting the verb is worth nothing if the target is lost -- the target is what the prose
    is written toward."""
    from h3ir.licence import transform_target
    assert transform_target(Brief(intent=intent)) == expect


def test_a_bare_adjective_is_still_not_a_transformation_after_the_inflection_fix():
    """The control. Widening the verb set must not widen it into ordinary description -- the whole
    asymmetry rests on a bare style word NOT counting."""
    from h3ir.licence import transformation_intent
    for intent in ("the man walks down the corridor, anime style",
                   "a cinematic, moody shot of the man walking",
                   "the man walks, stylised and painterly"):
        assert transformation_intent(Brief(intent=intent)) is None, intent


def test_no_reference_means_nothing_was_transformed_from_anything():
    """With no visual reference the request governs the medium by DEFAULT -- there is nothing to
    defer to. But `medium_transferred` read that default as a transformation, so a text-only brief
    reported: "the request asks for a transformation (None), so ... the plate's retention marker is
    attribute_transfer". It printed the phrase as None and asserted a marker for a plate the
    manifest does not contain. Seen on a real compile of "a woman steps off a night bus in the rain".
    """
    from h3ir.licence import MEDIUM
    lic = resolve_licence(Brief(intent="a woman steps off a night bus in the rain"), {})
    assert lic.governs[MEDIUM] == "request"      # unchanged: the request does govern by default
    assert lic.transform_phrase is None
    assert lic.medium_transferred is False       # but nothing was transferred
    assert lic.note() is None


def test_a_non_visual_reference_is_not_a_transformation():
    """`has_visual_ref` is false for an audio-only card, which flipped `medium_transferred` on and
    made the old `marker_for_plate` hand back `attribute_transfer` -- a marker from the VISUAL
    vocabulary -- for an asset with no image in it. The marker path is gone (§43); the gate that
    prevented it is still the thing worth asserting, because `note()` reads the same flag."""
    cards = {"aud": AssetCard(sha256="aud", kind=AssetKind.AUDIO)}
    lic = resolve_licence(Brief(intent="a woman steps off a night bus"), cards)
    assert lic.medium_transferred is False
    assert lic.note() is None




# ---------------------------------------------------------------------------
# "Explicitly speaks to" is a detector, and it was wrong in BOTH directions.
# The narrow direction was the one reported; the wide direction fires on the
# word "that", and it is the one with a mechanical consequence.
# ---------------------------------------------------------------------------

# `_mentions` tested `word in text`, so every listed word also matched every longer word that
# happened to contain it. These name no attribute whatsoever. The comment beside each is the
# listed word it collided with.
ORDINARY_ENGLISH_NAMING_NO_ATTRIBUTE = (
    "the man walks down the stone corridor that leads to the door",   # that      <- hat
    "what he does next is walk away",                                 # what      <- hat
    "a landscape opens up as he walks",                               # landscape <- cap
    "he addresses the crowd",                                         # addresses <- dress
    "the guard walks in pursuit of him",                              # pursuit   <- suit
    "a little girl walks past him",                                   # little    <- lit
    "high quality footage of a man walking",                          # quality   <- lit
    "a military parade marches past",                                 # military  <- lit
    "the elite guard turns to watch",                                 # elite     <- lit
)






# --------------------------------------------------------------- the narrow direction, per attribute

WARDROBE_PHRASINGS = (
    "the man walks, now in a leather blazer",
    "he walks down the corridor wearing sunglasses",
    "put him in a hoodie",
    "change his outfit to something darker",
    "she walks in, dressed in a kimono",
    "swap his waistcoat for a cardigan",
)


@pytest.mark.parametrize("intent", WARDROBE_PHRASINGS)
def test_a_request_that_speaks_to_clothing_takes_the_wardrobe(intent):
    """Only "now wearing a red jacket" was detected, because only its noun was listed. `blazer`,
    `waistcoat`, `cardigan`, `kimono` and `sunglasses` were not -- and for wardrobe a miss is not
    cosmetic. It re-opens the exact collision R15 was fixed for: the compiler goes on insisting the
    prose restate the plate's t-shirt against a request whose purpose is to replace it.

    The noun space is unbounded, so detection cannot rest on the nouns alone -- the CONSTRUCTIONS
    ("wearing", "dressed in", "put him in", "outfit", "swap ... for") are what close it.
    """
    from h3ir.compile import _wardrobe_terms
    from h3ir.licence import WARDROBE

    class _Plan:
        subjects = [SubjectPlan(label="<Subject 1>", descriptor="the man", kind="person",
                                attributes=["navy blue t-shirt", "dark blue jeans"], sources=[])]

    lic = resolve_licence(_brief(intent=intent), {"char": _card_with_style("live-action")})
    assert lic.governs[WARDROBE] == "request", intent
    assert _wardrobe_terms(_Plan(), lic) == (), "the plate's garments must not be re-asserted"


ATTRIBUTE_PHRASINGS = (
    ("lighting", "harsh fluorescent light from above"),
    ("lighting", "he waits under a streetlamp"),
    ("lighting", "the room is candlelit"),
    ("lighting", "a single bare bulb overhead, dimly lit"),
    ("framing", "shot from behind as he walks away"),
    ("framing", "extreme close up on her hands"),
    ("framing", "a two shot of them talking"),
    ("framing", "seen from a low angle"),
    ("palette", "muted greens and greys throughout"),
    ("palette", "a high contrast colour grade"),
    ("palette", "graded cold and desaturated"),
)


@pytest.mark.parametrize("attr,intent", ATTRIBUTE_PHRASINGS)
def test_a_request_that_names_an_attribute_is_not_silent_about_it(attr, intent):
    """Lighting, framing and palette reach only the sentence in the ask -- there is no mechanism
    behind them, which is why they rank below wardrobe. They still have to be right: naming an
    attribute in the list of things the references govern is the wrong emphasis for an attribute the
    caller just specified.

    Framing is anchored on a camera word on purpose. "from above" alone is how LIGHTING gets
    described ("light from above"), and "shot" alone is how a treatment word rides ("a cinematic
    shot of the man"), so the signal is `shot from` / `seen from` / an angle, never a bare direction.
    """
    lic = resolve_licence(_brief(intent=intent), {"char": _card_with_style("live-action")})
    assert lic.governs[attr] == "request", f"{intent!r}: {lic.reasons[attr]}"


ACTION_PHRASINGS = (
    "he sprints toward the door",
    "she leans against the wall",
    "he drops the torch",
    "she waves at the camera",
    "he collapses onto the floor",
    "she reaches out and grabs his arm",
)


@pytest.mark.parametrize("intent", ACTION_PHRASINGS)
def test_a_request_that_states_what_the_body_does_takes_the_action(intent):
    """The verb space is genuinely open, unlike the transforming verbs -- English has thousands of
    action verbs and a closed list of eight ways to say "restyle". So this list will never be
    complete, and it does not have to be: `governs[ACTION]` reaches nothing but the sentence in the
    ask. Ranked and treated accordingly -- the common verbs, correctly inflected, and no chase.
    """
    from h3ir.licence import ACTION
    lic = resolve_licence(_brief(intent=intent), {"char": _card_with_style("live-action")})
    assert lic.governs[ACTION] == "request", intent


# Hand-written from the dictionary, NOT generated by the same helper the pattern uses. §41's trap was
# an author whose regex and tests came out of one mental sentence, so they agreed with each other and
# covered a sixth of the input. An independent table is the only thing that catches a bad expansion.
INDEPENDENT_VERB_FORMS = {
    "walk": ("walks", "walked", "walking"),
    "run": ("runs", "ran", "running"),
    "sit": ("sits", "sat", "sitting"),
    "stand": ("stands", "stood", "standing"),
    "swim": ("swims", "swam", "swimming"),
    "fall": ("falls", "fell", "falling"),
    "throw": ("throws", "threw", "thrown", "throwing"),
    "speak": ("speaks", "spoke", "spoken", "speaking"),
    "drop": ("drops", "dropped", "dropping"),
    "step": ("steps", "stepped", "stepping"),
    "spin": ("spins", "spun", "spinning"),
    "grab": ("grabs", "grabbed", "grabbing"),
    "stride": ("strides", "strode", "striding"),
    "wave": ("waves", "waved", "waving"),
    "crouch": ("crouches", "crouched", "crouching"),
    "reach": ("reaches", "reached", "reaching"),
    "lean": ("leans", "leaned", "leaning"),
    "sprint": ("sprints", "sprinted", "sprinting"),
    "carry": ("carries", "carried", "carrying"),
    "kneel": ("kneels", "knelt", "kneeling"),
}


@pytest.mark.parametrize("base", sorted(INDEPENDENT_VERB_FORMS))
def test_every_action_verb_is_detected_in_every_inflection(base):
    """§41 again, one list over. `\\bswims\\b` matched "swims" and missed "swimming"; `stands? up`
    needed the preposition; `crouch(?:es|ing)?` had no past tense. Half the entries were inflected by
    hand and the halves disagreed, which is what a hand-written alternation always ends up doing.
    """
    from h3ir.licence import ACTION
    cards = {"char": _card_with_style("live-action")}
    for form in (base, *INDEPENDENT_VERB_FORMS[base]):
        lic = resolve_licence(_brief(intent=f"the man {form} across the room"), cards)
        assert lic.governs[ACTION] == "request", form


# --------------------------------------------------------------- the control

# Ordinary description. Every one of these must leave all four detector-driven attributes with the
# reference, because the whole asymmetry rests on description NOT counting as instruction. The two
# style briefs are the same three bare adjectives the transformation control guards, checked here
# against the OTHER five detectors.
NAMES_NOTHING_BUT_THE_ACTION = (
    "the man walks forward down the stone corridor",
    "a woman steps off a night bus in the rain and realises she left her bag on board",
    "he waits in a stone corridor while the door opens",
    "a cinematic, moody shot of the man walking",
    "the man walks, stylised and painterly",
    "the man walks down the corridor, anime style",
)




# --------------------------------------------------------------- the other consumer: the ask





# ---------------------------------------------------------------------------
# The other half of the same cause: the compiler asserted a marker the spec
# defines as something else, and nothing verified the channel that does carry
# the intent. Found by reading a live artifact, settled by reading the spec.
# ---------------------------------------------------------------------------

def test_the_spec_defines_attribute_transfer_as_a_DIFFERENT_target_subject():
    """The citation, machine-checked, because this is the sentence the whole reversal rests on and a
    convention recorded in prose constrains nobody (§38).

    `ref-en.txt` §4.1 is the authority, and it does not say "identity carried, look replaced" — the
    reading this project built on for two entries. It says the characteristics move to a DIFFERENT
    identifiable target subject. Restyling the same man is not that. If MiniMax ever redefines the
    marker, this test is where we find out instead of inferring it again.
    """
    from pathlib import Path
    spec = Path(__file__).resolve().parents[1].joinpath("h3ir", "prompts", "ref-en.txt").read_text()
    row = next(l for l in spec.splitlines() if l.startswith("| `attribute_transfer`"))
    assert "different identifiable target subject" in row.lower(), row
    # and the marker that DOES cover "still used, some characteristics changed"
    partial = next(l for l in spec.splitlines() if l.startswith("| `partially_preserved`"))
    assert "some defined characteristics are changed" in partial.lower(), partial


def test_the_medium_travels_through_the_style_opening_not_the_marker():
    """What the model does when left alone, measured across five live runs rather than argued.

    Five compiles of "the man from the sheet walks down a stone corridor lit by a wall torch,
    reimagined as a 1990s cel animation" against the live endpoint: **5/5 wrote `fully_preserved`**
    for <Subject 1> and **5/5 opened detailed_description with the requested medium**. One of them
    reconciled both in the retention line itself — "retained and animated in a 1990s cel style".

    So the model reads §4.1 correctly and puts the medium where the spec puts it. The compiler's
    `attribute_transfer` claim was the thing that disagreed with the format. This freezes one of those
    real artifacts as the fixture.
    """
    from pathlib import Path
    art = Path(__file__).resolve().parents[1].joinpath(
        "h3ir", "golden", "live_transformation_ref2va.txt").read_text()
    retention = art.split("retention_analysis:", 1)[1].split("detailed_description:", 1)[0]
    assert "attribute_transfer" not in retention
    assert "fully_preserved" in retention
    opening = art.split("detailed_description:", 1)[1].strip().splitlines()[0]
    assert "cel animation" in opening.lower(), opening


# --------------------------------------------------------------- R23: did the intent actually travel

def _transformation_ctx(**kw):
    """A Ref2VA context for a request that asked to depart from a 2d-animation plate."""
    base = dict(n_pictures=1, transformed_from="2d-animation")
    base.update(kw)
    return Context(**base)


def _art(opening: str) -> str:
    return ("subject_definitions:\n<Subject 1> is the man in <Picture 1>, with a shaved head.\n\n"
            "summary:\n[reference generation] The target video shows <Subject 1>.\n\n"
            "retention_analysis:\n<Subject 1> (appears in [Shot 1]): fully_preserved - the shaved head is "
            "retained.\n\ndetailed_description:\n" + opening + "\n"
            "[Shot 1] <Subject 1> walks forward with a slow push in.\n\n"
            "overall_soundscape:\nWind.\n\nnon_diegetic_music:\nN/A\n")




def _real_brief_style():
    """The live brief, its real analysed plate style, and the resolved decision."""
    card = AssetCard(sha256="c", kind=AssetKind.IMAGE,
                     style="Digital illustration, semi-realistic character design.",
                     subjects=[{"kind": "person", "descriptor": "the man",
                                "attributes": ["charcoal technical jacket"]}])
    ref = AssetRef(kind=AssetKind.IMAGE, role=Role.SUBJECT, sha256="c", px=(700, 480))
    brief = Brief(intent="the man from the sheet walks down a stone corridor lit by a wall torch, "
                         "reimagined as a 1990s cel animation", seconds=8, assets=[ref])
    lic = resolve_licence(brief, {"c": card})
    return lic, resolve_style(brief, {"c": card}, lic)






def test_R23_does_not_fire_on_a_real_live_transformation_compile():
    """The false-positive guard, on real model output and through the REAL arming decision rather than
    a Context I hand-built. Bypassing `_transformed_from` is what let the first version look fine."""
    from pathlib import Path

    from h3ir.compile import _transformed_from
    lic, style = _real_brief_style()
    art = Path(__file__).resolve().parents[1].joinpath(
        "h3ir", "golden", "live_transformation_ref2va.txt").read_text()
    fired = {f.rule for f in validate(art, Context(
        n_pictures=1, mode="ref2va", transformed_from=_transformed_from(style, lic)))}
    assert "R23-transformation-not-in-style-opening" not in fired


def test_R23_is_silent_when_no_transformation_was_asked_for():
    """No transformation means no expectation. The reference's medium in the opening is then exactly
    right, and firing there would fight `style.py`'s own output."""
    fired = {f.rule for f in validate(_art(
        "The target video is a stylised comic illustration with clean ink linework."),
        Context(n_pictures=1))}
    assert "R23-transformation-not-in-style-opening" not in fired
