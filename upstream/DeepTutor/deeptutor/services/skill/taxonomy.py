"""
Skill classification taxonomy
=============================

The single Python source of truth for EduHub's skill classification — the
required ``track`` (one-of) plus the optional faceting dimensions
(``language``, ``domains``, ``stages``, ``forms``, ``audiences``). It mirrors
the eduhub web's ``src/data/taxonomy.ts`` (now maintained in zzhtx258/eduhub,
``packages/eduhub-web``) value-by-value so the interactive
``skill publish`` / ``skill update`` flows can prompt with the same labels the
web upload form and ``/api/v1`` validation use.

Values are the lowercase tokens the API expects; the ``zh``/``en`` labels are
display-only. ``domains`` is a two-level tree: a top-level slug (``arts``) or a
dotted child (``arts.instruments``). Anything finer than a child belongs in
free-form ``tags``, not here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Option:
    """One taxonomy choice: the API token plus bilingual display labels."""

    value: str
    zh: str
    en: str

    def label(self, locale: str = "en") -> str:
        return self.en if locale == "en" else self.zh


@dataclass(frozen=True, slots=True)
class DomainNode:
    """A top-level domain and its dotted children."""

    value: str
    zh: str
    en: str
    children: tuple[Option, ...] = ()

    def label(self, locale: str = "en") -> str:
        return self.en if locale == "en" else self.zh


# ── required: track (single-select) ───────────────────────────────────────

TRACK_OPTIONS: tuple[Option, ...] = (
    Option("academics", "Academics", "Academics"),
    Option("companions", "Companions", "Companions"),
    Option("skills-interests", "Skills & Interests", "Skills & Interests"),
    Option("educators", "For Educators", "For Educators"),
)

# ── required: language (single-select, defaults to en) ─────────────────────

LANGUAGE_OPTIONS: tuple[Option, ...] = (
    Option("zh", "Chinese", "Chinese"),
    Option("en", "English", "English"),
    Option("ja", "Japanese", "Japanese"),
    Option("other", "Other", "Other"),
)

# ── optional: stage (multi-select) ─────────────────────────────────────────

STAGE_OPTIONS: tuple[Option, ...] = (
    Option("preschool", "Preschool", "Preschool"),
    Option("primary", "Primary", "Primary"),
    Option("junior-high", "Junior High", "Junior High"),
    Option("senior-high", "Senior High", "Senior High"),
    Option("university", "University", "University"),
    Option("adult", "Adult", "Adult"),
)

# ── optional: form (multi-select) ──────────────────────────────────────────

FORM_OPTIONS: tuple[Option, ...] = (
    Option("tutor", "Tutoring", "Tutoring"),
    Option("practice", "Practice", "Practice"),
    Option("feedback", "Feedback", "Feedback"),
    Option("assessment", "Assessment", "Assessment"),
    Option("planning", "Planning", "Planning"),
    Option("companion", "Companion", "Companion"),
    Option("tool", "Tool", "Tool"),
    Option("reference", "Reference", "Reference"),
)

# ── optional: audience (multi-select, empty means learners) ────────────────

AUDIENCE_OPTIONS: tuple[Option, ...] = (
    Option("learner", "Learners", "Learners"),
    Option("teacher", "Teachers", "Teachers"),
    Option("parent", "Parents", "Parents"),
)

# ── optional: domains (multi-select, two-level tree) ───────────────────────


def _domain(value: str, zh: str, en: str, children: list[tuple[str, str, str]]) -> DomainNode:
    return DomainNode(
        value=value,
        zh=zh,
        en=en,
        children=tuple(Option(f"{value}.{c}", czh, cen) for c, czh, cen in children),
    )


DOMAIN_TREE: tuple[DomainNode, ...] = (
    _domain(
        "lang-lit",
        "Languages & Literature",
        "Languages & Literature",
        [
            ("chinese", "Chinese", "Chinese"),
            ("english", "English", "English"),
            ("japanese", "Japanese", "Japanese"),
            ("korean", "Korean", "Korean"),
            ("french", "French", "French"),
            ("german", "German", "German"),
            ("spanish", "Spanish", "Spanish"),
            ("other-lang", "Other Languages", "Other Languages"),
            ("reading", "Literature & Reading", "Literature & Reading"),
        ],
    ),
    _domain(
        "math",
        "Math & Logic",
        "Math & Logic",
        [
            ("arithmetic", "Early Math", "Early Math"),
            ("algebra", "Algebra", "Algebra"),
            ("geometry", "Geometry", "Geometry"),
            ("calculus", "Calculus", "Calculus"),
            ("statistics", "Statistics", "Statistics"),
            ("competition", "Competition Math", "Competition Math"),
            ("logic", "Logic", "Logic"),
        ],
    ),
    _domain(
        "science",
        "Natural Sciences",
        "Natural Sciences",
        [
            ("physics", "Physics", "Physics"),
            ("chemistry", "Chemistry", "Chemistry"),
            ("biology", "Biology", "Biology"),
            ("earth-astro", "Earth & Astronomy", "Earth & Astronomy"),
        ],
    ),
    _domain(
        "computing",
        "Computing & Data",
        "Computing & Data",
        [
            ("programming", "Programming Basics", "Programming Basics"),
            ("software", "Software Development", "Software Development"),
            ("data-science", "Data Science", "Data Science"),
            ("ai", "AI", "AI"),
            ("security", "Security", "Security"),
            ("oi", "Competitive Programming", "Competitive Programming"),
        ],
    ),
    _domain(
        "humanities",
        "Humanities & Social Sciences",
        "Humanities & Social Sciences",
        [
            ("history", "History", "History"),
            ("geography", "Geography", "Geography"),
            ("civics", "Civics", "Civics"),
            ("philosophy", "Philosophy", "Philosophy"),
            ("psychology", "Psychology", "Psychology"),
            ("economics", "Economics", "Economics"),
            ("law", "Law", "Law"),
        ],
    ),
    _domain(
        "arts",
        "Arts & Creativity",
        "Arts & Creativity",
        [
            ("music-theory", "Music Theory", "Music Theory"),
            ("instruments", "Instruments", "Instruments"),
            ("vocal", "Vocal", "Vocal"),
            ("painting", "Painting", "Painting"),
            ("calligraphy", "Calligraphy", "Calligraphy"),
            ("design", "Design", "Design"),
            ("photography", "Photography", "Photography"),
            ("creative-writing", "Creative Writing", "Creative Writing"),
        ],
    ),
    _domain(
        "general",
        "General Skills",
        "General Skills",
        [
            ("speaking", "Public Speaking", "Public Speaking"),
            ("debate", "Debate", "Debate"),
            ("writing", "Writing", "Writing"),
            ("info-literacy", "Information Literacy", "Information Literacy"),
            ("memory", "Memory & Speed Reading", "Memory & Speed Reading"),
        ],
    ),
    _domain(
        "business",
        "Business & Careers",
        "Business & Careers",
        [
            ("office", "Office Skills", "Office Skills"),
            ("data-analysis", "Data Analysis", "Data Analysis"),
            ("media", "Digital Media", "Digital Media"),
            ("management", "Management", "Management"),
            ("finance", "Finance & Accounting", "Finance & Accounting"),
            ("career", "Career & Interviews", "Career & Interviews"),
        ],
    ),
    _domain(
        "life",
        "Life & Hobbies",
        "Life & Hobbies",
        [
            ("cooking", "Cooking", "Cooking"),
            ("fitness", "Fitness", "Fitness"),
            ("crafts", "Crafts & Gardening", "Crafts & Gardening"),
            ("games", "Board Games", "Board Games"),
            ("personal-finance", "Personal Finance", "Personal Finance"),
            ("life-skills", "Life Skills", "Life Skills"),
        ],
    ),
    _domain(
        "wellbeing",
        "Mind & Wellbeing",
        "Mind & Wellbeing",
        [
            ("mind", "Mental & Emotional", "Mental & Emotional"),
            ("mindfulness", "Mindfulness", "Mindfulness"),
            ("parenting", "Parenting", "Parenting"),
            ("communication", "Communication", "Communication"),
        ],
    ),
    _domain(
        "engineering",
        "Engineering & Making",
        "Engineering & Making",
        [
            ("robotics", "Robotics", "Robotics"),
            ("electronics", "Electronics", "Electronics"),
            ("printing-3d", "3D Printing & Modeling", "3D Printing & Modeling"),
            ("drones", "Drones & Models", "Drones & Models"),
        ],
    ),
)


# ── lookup / validation helpers ────────────────────────────────────────────

TRACK_VALUES: frozenset[str] = frozenset(o.value for o in TRACK_OPTIONS)
LANGUAGE_VALUES: frozenset[str] = frozenset(o.value for o in LANGUAGE_OPTIONS)
STAGE_VALUES: frozenset[str] = frozenset(o.value for o in STAGE_OPTIONS)
FORM_VALUES: frozenset[str] = frozenset(o.value for o in FORM_OPTIONS)
AUDIENCE_VALUES: frozenset[str] = frozenset(o.value for o in AUDIENCE_OPTIONS)

DOMAIN_VALUES: frozenset[str] = frozenset(
    [node.value for node in DOMAIN_TREE]
    + [child.value for node in DOMAIN_TREE for child in node.children]
)


def is_valid_track(value: str) -> bool:
    return value in TRACK_VALUES


def track_label(value: str, locale: str = "en") -> str:
    for o in TRACK_OPTIONS:
        if o.value == value:
            return o.label(locale)
    return value


def domain_label(value: str, locale: str = "en") -> str:
    """Leaf label: ``arts.instruments`` -> Instruments, ``arts`` -> Arts and Creativity."""
    root = value.split(".")[0]
    for node in DOMAIN_TREE:
        if node.value == root:
            if node.value == value:
                return node.label(locale)
            for child in node.children:
                if child.value == value:
                    return child.label(locale)
    return value


__all__ = [
    "AUDIENCE_OPTIONS",
    "AUDIENCE_VALUES",
    "DOMAIN_TREE",
    "DOMAIN_VALUES",
    "DomainNode",
    "FORM_OPTIONS",
    "FORM_VALUES",
    "LANGUAGE_OPTIONS",
    "LANGUAGE_VALUES",
    "Option",
    "STAGE_OPTIONS",
    "STAGE_VALUES",
    "TRACK_OPTIONS",
    "TRACK_VALUES",
    "domain_label",
    "is_valid_track",
    "track_label",
]
