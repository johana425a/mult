"""DeepSteam 2026-10-15: first-run interface/reply language follows the OS.

Usage: python patch_first_run_language.py <DeepSteam root>

Only affects an installation that has not been initialised yet (no
.deepsteam-defaults-v1.json); existing preferences are never touched.
"""
import py_compile
import sys
import tempfile
from pathlib import Path

MARK = "def system_languages()"

FUNC = '''

# Reply languages DeepTutor accepts besides en/zh/zh-tw (core/response_languages.py).
_REPLY_LANGUAGES = ("ja", "ko", "es", "fr", "de", "ru", "pt", "it", "ar", "pl", "uk", "ms")
_WINDOWS_LANGUAGE_NAMES = {
    "chinese": "zh", "english": "en", "japanese": "ja", "korean": "ko", "spanish": "es",
    "french": "fr", "german": "de", "russian": "ru", "portuguese": "pt", "italian": "it",
    "arabic": "ar", "polish": "pl", "ukrainian": "uk", "malay": "ms",
}


def system_languages() -> tuple[str, str]:
    """Interface and reply language for a first run, taken from the OS language.

    The interface ships in Chinese and English, so Chinese systems get the
    Chinese interface and every other system gets English. Replies use the
    system language whenever DeepTutor supports it, otherwise English.
    """
    import locale

    tag = ""
    try:
        import ctypes

        tag = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
    except Exception:
        pass
    if not tag:
        try:
            tag = locale.getlocale()[0] or ""
        except Exception:
            tag = ""
    tag = tag.replace("-", "_").lower()
    base = tag.split("_")[0]
    base = _WINDOWS_LANGUAGE_NAMES.get(base.split(" ")[0].split("(")[0], base)
    if base == "zh":
        traditional = any(part in tag for part in ("_tw", "_hk", "_mo", "hant", "traditional"))
        return "zh", "zh-tw" if traditional else "zh"
    return "en", base if base in _REPLY_LANGUAGES else "en"
'''


def main() -> None:
    path = Path(sys.argv[1]) / "scripts" / "initialize_deepsteam.py"
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        print("unchanged", path)
        return
    anchor_import = "import deeptutor_runtime as runtime\n"
    old_update = '    update_ui_settings({"theme": "dark", "language": "zh", "response_language": "zh"})\n'
    old_result = ('    result = {"initialized": True, "version": 1, "theme": "dark",\n'
                  '              "language": "zh", "response_language": "zh",\n')
    for anchor in (anchor_import, old_update, old_result):
        if text.count(anchor) != 1:
            raise SystemExit(f"anchor not found exactly once: {anchor!r}")
    text = text.replace(anchor_import, anchor_import + FUNC)
    text = text.replace(old_update,
                        '    interface_language, reply_language = system_languages()\n'
                        '    update_ui_settings({"theme": "dark", "language": interface_language,\n'
                        '                        "response_language": reply_language})\n')
    text = text.replace(old_result,
                        '    result = {"initialized": True, "version": 1, "theme": "dark",\n'
                        '              "language": interface_language, "response_language": reply_language,\n')
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
        handle.write(text)
    py_compile.compile(handle.name, doraise=True)
    Path(handle.name).unlink()
    path.write_text(text, encoding="utf-8", newline="")
    print("patched", path)


if __name__ == "__main__":
    main()
