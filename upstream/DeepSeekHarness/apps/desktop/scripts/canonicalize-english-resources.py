"""Reuse canonical English dictionaries in an English-only source release."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
SCOPES = [ROOT / "packages/client", ROOT / "apps"]
CJK = re.compile(r"[\u3400-\u9fff]")


def closing_brace(text: str, start: int) -> int:
    depth = 0
    quote = None
    comment = None
    i = start
    while i < len(text):
        c = text[i]
        pair = text[i:i + 2]
        if comment == "line":
            if c == "\n":
                comment = None
        elif comment == "block":
            if pair == "*/":
                comment = None
                i += 1
        elif quote:
            if c == "\\":
                i += 1
            elif c == quote:
                quote = None
        elif pair == "//":
            comment = "line"
            i += 1
        elif pair == "/*":
            comment = "block"
            i += 1
        elif c in "'\"`":
            quote = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("Unterminated object literal")


def assignments(text: str) -> dict[str, tuple[int, int]]:
    result = {}
    for match in re.finditer(r"(?:export\s+)?const\s+(\w+)[^=;]*=\s*(\{)", text):
        start = match.start(2)
        result[match.group(1)] = (start, closing_brace(text, start))
    return result


def normalize(text: str) -> str:
    objects = assignments(text)
    replacements = []
    pairs = [("zh", "en"), ("onboardingCopy", "onboardingEnglishCopy")]
    pairs.extend((name, name[:-2] + "En") for name in objects if name.endswith("Zh"))
    for legacy, canonical in pairs:
        if legacy in objects and canonical in objects:
            start, end = objects[legacy]
            e_start, e_end = objects[canonical]
            if CJK.search(text[start:end]):
                replacements.append((start, end, text[e_start:e_end]))
    # A directory picker registers inline locale dictionaries rather than constants.
    en = re.search(r"\[\s*'en'\s*,\s*(\{)", text)
    zh = re.search(r"\[\s*'zh'\s*,\s*(\{)", text)
    if en and zh:
        start, end = zh.start(1), closing_brace(text, zh.start(1))
        e_start, e_end = en.start(1), closing_brace(text, en.start(1))
        if CJK.search(text[start:end]):
            replacements.append((start, end, text[e_start:e_end]))
    for start, end, value in sorted(replacements, reverse=True):
        text = text[:start] + value + text[end:]
    return text


changed = []
for scope in SCOPES:
    for path in scope.rglob("*.ts"):
        if "tests" in path.parts or "stress-tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        normalized = normalize(text)
        if normalized != text:
            path.write_text(normalized, encoding="utf-8", newline="\n")
            changed.append(str(path.relative_to(ROOT)))

# The shared dictionary derives its key type from the legacy export. Copy the
# canonical literal rather than creating a circular value dependency.
common = ROOT / "packages/client/locale/src/locales"
en_text = (common / "en.ts").read_text(encoding="utf-8")
en_start, en_end = assignments(en_text)["en"]
(common / "zh.ts").write_text(
    "/** English compatibility dictionary and common key source. */\n"
    + "export const zh = " + en_text[en_start:en_end] + " as const\n\n"
    + "export type CommonKey = keyof typeof zh\n",
    encoding="utf-8", newline="\n",
)
changed.append("packages/client/locale/src/locales/zh.ts")

# NSIS keeps the language identifiers for package compatibility, with English
# copy for every supported identifier.
installer = ROOT / "apps/desktop/installer/strings.nsh"
installer_text = installer.read_text(encoding="utf-8")
english = dict(re.findall(r'^LangString (\w+) \$\{LANG_ENGLISH\} (.+)$', installer_text, re.M))
installer_text = re.sub(
    r'^LangString (\w+) \$\{LANG_SIMPCHINESE\} .+$',
    lambda m: f"LangString {m[1]} ${{LANG_SIMPCHINESE}} {english[m[1]]}",
    installer_text, flags=re.M,
)
installer.write_text(installer_text, encoding="utf-8", newline="\n")
changed.append("apps/desktop/installer/strings.nsh")

print(f"Updated {len(changed)} canonical English resource files.")

# English documents do not link to omitted translated editions.
for scope in SCOPES:
    for path in scope.rglob("*.md"):
        if "tests" in path.parts or "stress-tests" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if not (
            line.startswith("English |") and "README.zh.md" in line
        )]
        normalized = "\n".join(lines) + "\n"
        if normalized != text:
            path.write_text(normalized, encoding="utf-8", newline="\n")
