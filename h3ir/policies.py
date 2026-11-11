"""本 Fork 的规则来源；作者附加策略始终关闭。"""
from __future__ import annotations

from .models import Finding

OFFICIAL_REVISION = "0919fb684102ef115126612f3fbb84d1027e7317"
OFFICIAL_GROUPS = {
    'ref:1': ('S1-missing-section', 'S2-section-order', 'S5-mode-field-crossed', 'S9-section-empty'),
    'base:2.1': ('I1-instruction-line-missing', 'I2-instruction-line-not-exact', 'I3-instruction-line-no-blank-line'),
    'ref:2': ('L1-unknown-label', 'L2-undefined-subject', 'L5-redundant-source-line', 'L6-label-not-closed'),
    'ref:3': ('M1-task-prefix', 'M2-task-type', 'M3-task-dupe', 'M4-new-label-in-summary', 'M5-editing-without-video', 'M6-editing-opening', 'M7-audio-reuse-without-audio', 'M8-audio-reference-without-audio', 'M11-keyframe-without-picture', 'M12-continuation-without-video'),
    'ref:4': ('R1-malformed-entry', 'R2-illegal-marker', 'R5-unanalysed-subject', 'R24-label-analysed-twice'),
    'base:4.2': ('T1-no-shot', 'T2-shot1-timestamp', 'T3-timestamp-format', 'T4-missing-cut-time', 'T5-non-increasing', 'T6-time-past-end', 'T8-shot-numbering'),
    'ref:5.2': ('P1-no-style-opening',),
    'base:4.1': ('P6-no-style-in-shot1',),
    'ref:5.4': ('R4-speaker-in-retention',),
    'ref:5.3': ('R19-bare-subject-name',),
    'base:4.4': ('D1-unbalanced-d', 'D2-missing-lang-tag', 'D3-speaker-numbering', 'D4-dialogue-not-verbatim', 'D5-marker-not-byte-exact', 'D8-speaker-gap', 'D9-voiceover-no-lips-clause', 'D11-split-line-no-scenetrans', 'D12-split-line-no-continuity-statement', 'A3-dialogue-outside-desc'),
    'base:4.6': ('A1-soundscape-length',),
    'base:4.7': ('A7-music-length',),
    'base:4.5': ('H2-onscreen-text-unquoted',),
}

USER_RULES = frozenset(('T11-shot-count-pinned', 'A4-music-should-be-na', 'M13-declared-edit-not-claimed', 'M14-declared-continuation-not-claimed'))
ENGINEERING_RULES = frozenset(('X8-enriched-rejected', 'X11-shot-plan-repaired', 'L3-phantom-media', 'T7-illegal-duration', 'W2-lora-trigger-missing', 'W6-lora-no-id', 'W7-lora-bad-trigger', 'W8-lora-no-trigger', 'W9-lora-duplicate-id', 'W10-lora-unknown', 'W11-lora-variant', 'W13-lora-file-missing', 'W16-lora-sha-unverified', 'W17-lora-sha-mismatch', 'X1-render-determinism', 'X5-render-note', 'X9-model-unavailable-midway', 'X10-anchor-role-downgraded', 'X12-brief-repaired', 'X13-written-rejected', 'X14-finding-unfixable', 'X15-audio-uncharacterised', 'X16-assets-dropped-for-mode', 'X17-reference-video-truncated', 'X18-role-overrides-anchor-language', 'X19-duration-snapped', 'N1-director-empty', 'N2-director-unknown'))
DISABLED_AUTHOR_RULES = frozenset(('S3-preamble', 'S4-code-fence', 'M9-task-prefix-repeated', 'P2-too-short', 'P3-too-long', 'P7-cut-phrase-off-vocabulary', 'P8-camera-modifier-off-vocabulary', 'A5-music-no-tempo', 'M10-editing-opening-repeated', 'R3-missing-appears-in', 'D7-decorative-punctuation', 'A2-sound-duplicated', 'A6-paired-audio-short', 'A8-music-mood-word', 'D10-dialogue-line-duplicated', 'D13-line-split-without-a-cut', 'D14-reperformance-altered', 'D15-copied-audio-words-missing', 'D16-transcript-not-reperformed', 'G1-reasoning-leaked', 'G2-model-self-narration', 'H1-unicode-hazard', 'H3-token-band', 'L4-unused-media', 'M15-audio-reuse-without-a-copy-role', 'M16-task-prefix-not-derived', 'P4-no-camera-at-all', 'P5-camera-no-motion-type', 'P5b-camera-no-amplitude', 'P9-role-token-in-prose', 'Q1-forbidden-element-present', 'Q2-unlicensed-addition', 'Q3-extreme-not-honoured', 'R10-mode-role-contamination', 'R11-scope-not-cited', 'R12-pose-as-identity', 'R13-sheet-artefact', 'R14-inferred-attribute', 'R15-wardrobe-not-restated', 'R16-style-opening-malformed', 'R17-cut-states-nothing-new', 'R18-camera-as-label-stack', 'R20-camera-contradiction', 'R21-audio-provenance-invented', 'R22-audio-marker-role', 'R23-transformation-not-in-style-opening', 'R25-subject-defined-twice', 'R26-audio-described-as-a-frame', 'R27-reference-audio-claimed-as-copied', 'R28-storyboard-cited-as-content', 'R29-style-cited-as-content', 'R30-structure-cited-as-content', 'R31-replacement-not-recorded', 'R32-transfer-target-unnamed', 'R6-anchor-must-be-preserved', 'R7-picture-cannot-transfer', 'R8-edit-source-marker', 'R9-multiple-full-copies', 'S6-style-discrepancy', 'S7-transformation-intent', 'S8-planner-suggestion', 'T10-outside-trained-band', 'T12-cut-inside-the-floor', 'T9-first-shot-not-at-zero', 'W12-lora-constraint', 'W14-lora-strength-clamped', 'W15-lora-conflict', 'W3-lora-trigger-count', 'W4-lora-trigger-slot', 'X7-subject-not-cited'))

OFFICIAL_RULES = {rule: section for section, rules in OFFICIAL_GROUPS.items() for rule in rules}


def origin(rule: str) -> str:
    if rule in OFFICIAL_RULES:
        return "official"
    if rule in USER_RULES:
        return "user"
    if rule in ENGINEERING_RULES:
        return "engineering"
    return "author"


def enabled(rule: str) -> bool:
    return origin(rule) != "author"


def active_findings(findings: list[Finding]) -> list[Finding]:
    return [finding for finding in findings if enabled(finding.rule)]
