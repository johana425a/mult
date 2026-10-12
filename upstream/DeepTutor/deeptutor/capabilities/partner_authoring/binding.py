"""Objective intent gate for chat-native Partner profile authoring."""

from __future__ import annotations

import re

from deeptutor.core.context import UnifiedContext

PARTNER_AUTHORING_CAPABILITY_NAME = "partner_authoring"

# The action has to lead into the Partner object within one clause. Matching the two words
# anywhere in the message fired on turns that only mention a Partner ("I want to file an issue
# about the Partner bug"), and finish_instruction then forces a draft the user never asked for.
_EN_ACTION = (
    r"(?:\b(?:create|make|build|design|generate|add|set\s+up)\b(?:\s+(?:me|us))?"
    r"|\b(?:want|need)\b)"
)
_EN_DETERMINER = r"\s+(?:a|an|another|one|my\s+own|our\s+own|a\s+new|new)\b"
_EN_GAP = r"(?:\s+(?!(?:about|with|for|of|from|in|on|to|that|which)\b)[\w'-]+){0,3}?"
_EN_OBJECT = (
    r"\s+(?:partners?|companions?|tutors?|mentors?|coach(?:es)?|study\s+budd(?:y|ies))(?![\w-])"
)

_AUTHORING_REQUEST = re.compile(
    rf"{_EN_ACTION}{_EN_DETERMINER}{_EN_GAP}{_EN_OBJECT}",
    re.IGNORECASE,
)
_QUOTED_OR_CODE = re.compile(
    r"```[\s\S]*?```|~~~[\s\S]*?~~~"
    r"|(?m:^>[^\n]*)|`[^`\n]*`"
    r'|"[^"\n]*"|“[^”\n]*”|\u300c[^\u300d\n]*\u300d|\u300e[^\u300f\n]*\u300f'
    r"|(?<!\w)'[^'\n]+'(?!\w)"
)
_CLAUSE_END = re.compile(r"[\u3002\uff01\uff1f!?\uff1b;\uff0c,\n]")
_NEGATED_ACTION = re.compile(
    r"(?:\b(?:don't|do\s+not|never|not|can't|cannot)\s*(?:want|need)?(?:\s+(?:you\s+)?to)?\s*)$",
    re.IGNORECASE,
)
_MENTION_QUESTION = re.compile(
    r"^\s*(?:explain\s+)?(?:why|how|what)\b",
    re.IGNORECASE,
)
_NON_PARTNER_TARGET = re.compile(
    r"^\s+(?:issue|bug|report|checklist|style|tone|feature|setting|ticket)\b",
    re.IGNORECASE,
)


def partner_authoring_trigger(context: UnifiedContext) -> str | None:
    """Why this turn is in the authoring flow, or ``None`` when it is not.

    ``explicit`` means the user selected the capability; ``heuristic`` means only
    the keyword gate matched, which is a guess about the words they typed.
    """
    # Home/product Chat owns the review card and confirmation flow. A Partner
    # (including one running inside a Group) must not create drafts inside its
    # synthetic workspace merely because someone talks about another Partner.
    if context.metadata.get("source") == "partner":
        return None
    if context.active_capability == PARTNER_AUTHORING_CAPABILITY_NAME:
        return "explicit"
    text = str(context.user_message or "")
    quoted = [match.span() for match in _QUOTED_OR_CODE.finditer(text)]
    for match in _AUTHORING_REQUEST.finditer(text):
        # Mentioning a request inside a quotation or code sample is not an
        # instruction. The action may still be outside quotes around a name.
        if any(start <= match.start() and match.end() <= end for start, end in quoted):
            continue
        clause_start = max(
            (boundary.end() for boundary in _CLAUSE_END.finditer(text, 0, match.start())),
            default=0,
        )
        if _NEGATED_ACTION.search(text[clause_start : match.start()]):
            continue
        if _MENTION_QUESTION.search(text[clause_start : match.start()]):
            continue
        if _NON_PARTNER_TARGET.match(text[match.end() :]):
            continue
        return "heuristic"
    return None


def is_partner_authoring_turn(context: UnifiedContext) -> bool:
    return partner_authoring_trigger(context) is not None


__all__ = [
    "PARTNER_AUTHORING_CAPABILITY_NAME",
    "is_partner_authoring_turn",
    "partner_authoring_trigger",
]
