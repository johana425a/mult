"""Auditable model capacity metadata, separate from per-request output budgets.

No discovery or inference request is made here. Only exact official model IDs
with checked sources receive a capacity; an arbitrary custom model stays unknown.
"""
from __future__ import annotations

DEEPSEEK_LIMITS_SOURCE = 'deepseek-official-api-2026-10-11'
DEEPSEEK_ACCOUNT_LIMITS_SOURCE = 'deepseek-harness-d743267-account-catalog'
DEEPSEEK_CONTEXT_WINDOW = 1_000_000
DEEPSEEK_API_MAX_OUTPUT = 384_000
# The pinned official account adapter shares the 1M model catalog, but its
# documented per-request adapter cap is 256000. Do not assume API/account parity
# beyond that catalog, or turn the maximum into every request's output reserve.
DEEPSEEK_ACCOUNT_OUTPUT_CAP = 256_000
DEEPSEEK_MODEL_IDS = frozenset({
    'deepseek-flash', 'deepseek-v4-pro',
    'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp',
})


def managed_model_limits(model: str, route: str) -> dict:
    # Source: https://api-docs.deepseek.com/quick_start/pricing/ (1M / max384K).
    # Account: pinned official packages/llm/llm-deepseek/src/defaults.ts and
    # llm-deepseek-account/src/index.ts use the shared default catalog/options.
    if model not in DEEPSEEK_MODEL_IDS or route not in ('account', 'apikey'):
        return {}
    source = DEEPSEEK_ACCOUNT_LIMITS_SOURCE if route == 'account' else DEEPSEEK_LIMITS_SOURCE
    return {'context_window': DEEPSEEK_CONTEXT_WINDOW,
            'max_output_tokens': DEEPSEEK_ACCOUNT_OUTPUT_CAP if route == 'account' else DEEPSEEK_API_MAX_OUTPUT,
            'context_window_source': source}


def bundled_model_limits() -> dict:
    # This is the installed llama.cpp process's actual configured window, not
    # the potentially larger capacity advertised for another Qwen deployment.
    return {'context_window': 16384, 'max_output_tokens': 4096,
            'context_window_source': 'bundled-qwen-runtime-16384'}
