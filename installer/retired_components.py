"""Exact product-owned components excluded from current runtime payloads.

This is deliberately not a name/brand search: user-added local API models and
the independent document parser remain available.
"""
RETIRED_PREFIXES = ("models/local-qwen/", "runtime/local-qwen/", "integration/local_qwen/")
RETIRED_FILES = frozenset({"scripts/qwen_runtime.py", "scripts/local_qwen_compat.py",
                          "integration/check_local_qwen_defaults.py"})


def retired_program_path(name: str) -> bool:
    value = name.replace("\\", "/").casefold()
    return value in RETIRED_FILES or value.startswith(RETIRED_PREFIXES)


def assert_no_retired_components(names):
    leftovers = [name for name in names if retired_program_path(name)]
    if leftovers:
        raise RuntimeError("Retired built-in model remains in release: " + leftovers[0])
