"""Op-emit guards: banned-phrase filter + budgets.

Run at op-emit time (during the loop) so the model gets an observation
back when an op is rejected and can rewrite. Today's pre-redesign code
filtered banned phrases after the LLM call returned all ops at once,
which meant rejection was a silent drop.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import re
from typing import Iterable

from deeptutor.services.memory.ops import Op

logger = logging.getLogger(__name__)

# L3 objectivity guard: phrases the LLM is prompt-banned from emitting.
# Runtime enforces by dropping any L3 op whose text contains one of these
# (outside of verbatim user quotations). Logged as a warning so we
# can tune the list against real prompt regressions.
BANNED_PHRASES: tuple[str, ...] = (
    # English absolutes
    "deeply",
    "truly",
    "mastered",
    "expert in",
    "passionate",
    "loves",
    "hates",
    "always",
    "never",
    "fully understands",
    # Additional absolutist wording
    "profoundly",
    "completely",
    "perfect mastery",
    "perfect understanding",
    "complete understanding",
    "complete mastery",
    "Expert",
    "loves",
    "always",
    "never",
)


# Per-loop budgets. Beyond these the dispatcher emits a hint observation
# instead of executing the action; the prompt nudges the model to finish.
@dataclass(frozen=True)
class ToolBudgets:
    read_entity: int = 30
    search: int = 20
    list_pending: int = 50  # cheap nav, generous
    list_sections: int = 50
    recent_changes: int = 3
    add_entry: int = 12
    edit_entry: int = 12
    delete_entry: int = 12
    note: int = 8


_QUOTED_RE = re.compile(r"\u300c[^\u300d]*\u300d|\"[^\"]*\"")


def _has_banned(text: str) -> bool:
    """Return ``True`` iff a banned phrase appears outside every quote.

    Quoted regions in supported punctuation styles are stripped first, because
    the prompt allows verbatim user quotations to contain the otherwise-
    banned absolutes.
    """
    stripped = _QUOTED_RE.sub("", text).lower()
    for phrase in BANNED_PHRASES:
        if phrase in stripped:
            return True
    return False


def _op_text(op: Op) -> str:
    text = getattr(op, "text", "") or getattr(op, "new_text", "")
    return str(text)


def _filter_banned(ops: Iterable[Op]) -> list[Op]:
    """Drop ops whose text contains banned absolutist phrasing.

    Used post-loop as a safety net even though the per-op emit path
    already rejects them. Kept callable by name for legacy tests and
    the apply_ops_payload preview/apply round-trip.
    """
    kept: list[Op] = []
    for op in ops:
        text = _op_text(op)
        if text and _has_banned(text):
            logger.warning(
                "memory consolidate: dropped op with banned phrase: %s",
                text[:80],
            )
            continue
        kept.append(op)
    return kept
