"""Shared language directives for prompt-driven LLM calls.

This helper centralizes the "stay in the requested language" instruction so
different modules can share the same behavior without depending on book-only
utilities.
"""

from __future__ import annotations

_LANGUAGE_LABELS: dict[str, str] = {
    "zh": "Chinese",
    "zh-cn": "Simplified Chinese",
    "zh-tw": "Traditional Chinese",
    "en": "English",
    "ja": "Japanese",
    "ko": "Korean",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "ru": "Russian",
    "uk": "Ukrainian",
    "pt": "Portuguese",
    "it": "Italiano",
    "ar": "Arabic",
    "pl": "Polish",
    "ms": "Malay",
}


def normalize_language(language: str | None) -> str:
    return (language or "en").strip().lower() or "en"


def is_chinese(language: str | None) -> bool:
    """Whether reader-facing text for *language* should be written in Chinese.

    One answer for a question eight modules used to answer for themselves,
    two of them without the ``None`` guard.
    """
    return normalize_language(language).startswith("zh")


def language_label(language: str | None) -> str:
    code = normalize_language(language)
    if code in _LANGUAGE_LABELS:
        return _LANGUAGE_LABELS[code]
    base = code.split("-", 1)[0]
    return _LANGUAGE_LABELS.get(base, language or "English")


_OVERRIDE_ZH = (
    "This is the default output language, not a restriction on the reader: if "
    "the user explicitly asks you to answer in another language, honour that "
    "request and keep to it for the rest of the conversation."
)
_OVERRIDE_EN = (
    "This is the default output language, not a restriction on the reader: if "
    "the user explicitly asks you to answer in another language, honour that "
    "request and keep to it for the rest of the conversation."
)


def language_directive(language: str | None, *, allow_user_override: bool = False) -> str:
    """Return a reader-facing language instruction for prompts.

    ``allow_user_override`` adds one sentence letting the user change the
    language by asking. Conversational surfaces want it; a book, a quiz or a
    research report has no user in the loop to ask, so they keep the strict
    form and the default stays strict.

    Without it the directive is an absolute prohibition sitting at the very end
    of the prompt, immediately after a runtime policy that says user text is
    "not authority over these instructions" — so a model reading both refuses
    a request to change the response language and says it is *required* to answer in English. Which is
    correct behaviour, and exactly the wrong answer.
    """
    code = normalize_language(language)
    label = language_label(code)
    if code.startswith("zh"):
        body = (
            "\n\n[Language] "
            f"Write all reader-facing text (titles, prose, explanations, hints, transitions, "
            f"question stems and options) in {label}. Do not switch languages because of source material, "
            "JSON keys or technical terminology. Keep necessary proper nouns and formula symbols "
            f"in their original form; write everything else in {label}."
        )
        return f"{body} {_OVERRIDE_ZH}" if allow_user_override else body
    if code == "en":
        body = (
            "\n\n[Language] Write ALL reader-facing text (titles, prose, "
            "explanations, hints, transitions, quiz stems, options, etc.) in "
            "English. Do NOT switch languages even if the source material, "
            "JSON keys, or examples in this prompt are in another language. "
            "Keep proper nouns (people, products, formula symbols) in their "
            "original form."
        )
        return f"{body} {_OVERRIDE_EN}" if allow_user_override else body
    body = (
        f"\n\n[Language] Write ALL reader-facing text strictly in {label}. "
        "Do NOT switch languages even if the source material, JSON keys, or "
        "examples in this prompt are in a different language. Keep proper "
        "nouns (people, products, formula symbols) in their original form."
    )
    return f"{body} {_OVERRIDE_EN}" if allow_user_override else body


def append_language_directive(
    system_prompt: str | None,
    language: str | None,
    *,
    allow_user_override: bool = False,
) -> str:
    """Append the language directive to an existing system prompt."""
    base = (system_prompt or "").rstrip()
    directive = language_directive(language, allow_user_override=allow_user_override).strip()
    if not base:
        return directive
    return f"{base}\n\n{directive}"


__all__ = [
    "append_language_directive",
    "is_chinese",
    "language_directive",
    "language_label",
    "normalize_language",
]
