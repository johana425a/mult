"""Read-only install-directory boundaries for recorded process commands.

No code is executed or process is modified. Windows path rules are used even
in cross-platform deterministic fixtures because the shipped runtime is Windows.
"""
from __future__ import annotations

import ast
import ntpath


def path_in_install(value, root):
    """Require the directory itself or a descendant, never a sibling prefix."""
    if not isinstance(value, str):
        return False
    value = value.strip().strip('"')
    if not ntpath.isabs(value):
        return False
    candidate = ntpath.normcase(ntpath.normpath(value))
    base = ntpath.normcase(ntpath.normpath(str(root)))
    return candidate == base or candidate.startswith(base.rstrip('\\') + '\\')


def command_in_install(command, root):
    """Check direct path arguments and Python -c string constants safely.

    The portal launcher embeds repr(ROOT) in -c. Parsing its constants resolves
    doubled backslashes without broad substring matches or evaluating code.
    """
    if not isinstance(command, (list, tuple)):
        return False
    for index, value in enumerate(command):
        if path_in_install(value, root):
            return True
        if index and command[index - 1] == '-c' and isinstance(value, str):
            try:
                syntax = ast.parse(value)
            except (SyntaxError, ValueError, MemoryError, RecursionError):
                continue
            if any(isinstance(node, ast.Constant) and path_in_install(node.value, root)
                   for node in ast.walk(syntax)):
                return True
    return False
