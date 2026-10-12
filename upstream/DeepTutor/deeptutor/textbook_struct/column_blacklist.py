"""Closed vocabulary of textbook feature-column names (layer 0).

These are recurring textbook activity/column names — MinerU often classifies
them as ``title`` blocks, but they are never chapter headings. The list is
closed on purpose: no fuzzy matching, to avoid swallowing real titles.
Append new names as new textbook editions introduce new column types.
"""

COLUMN_BLACKLIST: frozenset[str] = frozenset(
    {
        # civics / politics
        "Explore and share",
        "Related links",
        "Expert commentary",
        "Glossary",
        "Viewpoint one",
        "Viewpoint two",
        "Viewpoint three",
        # Chinese / English
        "Study tip",
        "Unit introduction",
        "Think and investigate",
        # math / physics / chemistry / biology
        "Think",
        "Explore",
        "Experiment",
        "Practice",
        "Exercises",
        "Review and consolidate",
        "Chapter summary",
        "IT application",
        "Read and think",
        "Observe and think",
        # geography / history
        "Question study",
        "Self-study",
        "Activity",
        "Case study",
        "Knowledge window",
    }
)
