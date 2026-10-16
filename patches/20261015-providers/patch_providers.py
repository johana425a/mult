"""DeepSteam 2026-10-15: register more model providers for users worldwide.

Usage: python patch_providers.py <path-to-deeptutor-package-dir> [--check]

Edits four files inside the DeepTutor package in place. Every edit is anchored
on text that must occur exactly once, is skipped when the marker is already
present (idempotent), and the edited files are compiled before being written.
"""
from __future__ import annotations

import py_compile
import sys
import tempfile
from pathlib import Path

MARK = "DeepSteam 2026-10-15 providers"

NEW_SPECS = '''
    # === DeepSteam 2026-10-15 providers: worldwide coverage ================
    # Regional platforms of vendors already listed above. Keys are issued per
    # platform and are not interchangeable, so each region is its own entry.
    # Empty keywords: these never take over model-name detection from the
    # original entry, they only offer the right endpoint in the picker.
    ProviderSpec(
        name="moonshot_global",
        keywords=(),
        env_key="MOONSHOT_API_KEY",
        display_name="Moonshot / Kimi (global, platform.moonshot.ai)",
        backend="openai_compat",
        default_api_base="https://api.moonshot.ai/v1",
        model_overrides=(
            ("kimi", {"temperature": None}),
            ("^k3", {"temperature": None}),
        ),
    ),
    ProviderSpec(
        name="dashscope_intl",
        keywords=(),
        env_key="DASHSCOPE_API_KEY",
        display_name="Alibaba Cloud Model Studio / Qwen (Singapore)",
        backend="openai_compat",
        default_api_base="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        thinking_style="enable_thinking",
    ),
    ProviderSpec(
        name="dashscope_us",
        keywords=(),
        env_key="DASHSCOPE_API_KEY",
        display_name="Alibaba Cloud Model Studio / Qwen (US)",
        backend="openai_compat",
        default_api_base="https://dashscope-us.aliyuncs.com/compatible-mode/v1",
        thinking_style="enable_thinking",
    ),
    ProviderSpec(
        name="zai_global",
        keywords=(),
        env_key="ZAI_API_KEY",
        display_name="Z.ai / GLM (global)",
        backend="openai_compat",
        default_api_base="https://api.z.ai/api/paas/v4",
    ),
    ProviderSpec(
        name="minimax_cn",
        keywords=(),
        env_key="MINIMAX_API_KEY",
        display_name="MiniMax (China, minimaxi.com)",
        backend="openai_compat",
        default_api_base="https://api.minimaxi.com/v1",
        api_base_by_format=(("anthropic", "https://api.minimaxi.com/anthropic"),),
        thinking_style="reasoning_split",
    ),
    ProviderSpec(
        name="siliconflow_global",
        keywords=(),
        env_key="OPENAI_API_KEY",
        display_name="SiliconFlow (global, siliconflow.com)",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="api.siliconflow.com",
        default_api_base="https://api.siliconflow.com/v1",
    ),
    # Model vendors with their own OpenAI-compatible endpoint.
    ProviderSpec(
        name="xai",
        keywords=("grok",),
        env_key="XAI_API_KEY",
        display_name="xAI (Grok)",
        backend="openai_compat",
        default_api_base="https://api.x.ai/v1",
    ),
    ProviderSpec(
        name="cohere",
        keywords=("cohere", "command-a", "command-r"),
        env_key="COHERE_API_KEY",
        display_name="Cohere",
        backend="openai_compat",
        default_api_base="https://api.cohere.ai/compatibility/v1",
        supports_stream_options=False,
    ),
    ProviderSpec(
        name="perplexity",
        keywords=("sonar",),
        env_key="PERPLEXITY_API_KEY",
        display_name="Perplexity (Sonar)",
        backend="openai_compat",
        default_api_base="https://api.perplexity.ai",
        supports_stream_options=False,
    ),
    ProviderSpec(
        name="upstage",
        keywords=("upstage", "solar-pro", "solar-mini"),
        env_key="UPSTAGE_API_KEY",
        display_name="Upstage (Solar)",
        backend="openai_compat",
        default_api_base="https://api.upstage.ai/v1",
    ),
    ProviderSpec(
        name="hunyuan",
        keywords=("hunyuan",),
        env_key="HUNYUAN_API_KEY",
        display_name="Tencent Hunyuan 腾讯混元",
        backend="openai_compat",
        default_api_base="https://api.hunyuan.cloud.tencent.com/v1",
    ),
    ProviderSpec(
        name="baichuan",
        keywords=("baichuan",),
        env_key="BAICHUAN_API_KEY",
        display_name="Baichuan 百川智能",
        backend="openai_compat",
        default_api_base="https://api.baichuan-ai.com/v1",
    ),
    # Hosts and gateways serving many vendors' models.
    ProviderSpec(
        name="together",
        keywords=("together",),
        env_key="TOGETHER_API_KEY",
        display_name="Together AI",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="api.together.xyz",
        default_api_base="https://api.together.xyz/v1",
    ),
    ProviderSpec(
        name="fireworks",
        keywords=("fireworks",),
        env_key="FIREWORKS_API_KEY",
        display_name="Fireworks AI",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="api.fireworks.ai",
        default_api_base="https://api.fireworks.ai/inference/v1",
    ),
    ProviderSpec(
        name="deepinfra",
        keywords=("deepinfra",),
        env_key="DEEPINFRA_API_KEY",
        display_name="DeepInfra",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="api.deepinfra.com",
        default_api_base="https://api.deepinfra.com/v1/openai",
    ),
    ProviderSpec(
        name="cerebras",
        keywords=("cerebras",),
        env_key="CEREBRAS_API_KEY",
        display_name="Cerebras",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="api.cerebras.ai",
        default_api_base="https://api.cerebras.ai/v1",
    ),
    ProviderSpec(
        name="sambanova",
        keywords=("sambanova",),
        env_key="SAMBANOVA_API_KEY",
        display_name="SambaNova Cloud",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="api.sambanova.ai",
        default_api_base="https://api.sambanova.ai/v1",
    ),
    ProviderSpec(
        name="huggingface",
        keywords=("huggingface",),
        env_key="HF_TOKEN",
        display_name="Hugging Face Inference Providers",
        backend="openai_compat",
        is_gateway=True,
        detect_by_key_prefix="hf_",
        detect_by_base_keyword="router.huggingface.co",
        default_api_base="https://router.huggingface.co/v1",
    ),
    ProviderSpec(
        name="nebius",
        keywords=("nebius",),
        env_key="NEBIUS_API_KEY",
        display_name="Nebius Token Factory",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="nebius.com",
        default_api_base="https://api.tokenfactory.nebius.com/v1/",
    ),
    ProviderSpec(
        name="vercel_ai_gateway",
        keywords=("vercel",),
        env_key="AI_GATEWAY_API_KEY",
        display_name="Vercel AI Gateway",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="ai-gateway.vercel.sh",
        default_api_base="https://ai-gateway.vercel.sh/v1",
    ),
    ProviderSpec(
        name="github_models",
        keywords=("github_models",),
        env_key="GITHUB_TOKEN",
        display_name="GitHub Models",
        backend="openai_compat",
        is_gateway=True,
        detect_by_base_keyword="models.github.ai",
        default_api_base="https://models.github.ai/inference",
    ),
'''

NEW_ALIASES = '''    # DeepSteam 2026-10-15 providers
    "x_ai": "xai",
    "grok": "xai",
    "together_ai": "together",
    "togetherai": "together",
    "fireworks_ai": "fireworks",
    "hugging_face": "huggingface",
    "hf": "huggingface",
    "nebius_ai": "nebius",
    "vercel": "vercel_ai_gateway",
    "z_ai": "zai_global",
    "kimi": "moonshot_global",
    "moonshot_ai": "moonshot_global",
    "qwen_intl": "dashscope_intl",
    "model_studio": "dashscope_intl",
    "tencent_hunyuan": "hunyuan",
'''

CAPS = '''
# --- DeepSteam 2026-10-15 providers: capabilities for the added entries ------
# Regional platforms behave like their original platform.
for _variant, _origin in (
    ("moonshot_global", "moonshot"),
    ("dashscope_intl", "dashscope"),
    ("dashscope_us", "dashscope"),
    ("minimax_cn", "minimax"),
    ("siliconflow_global", "siliconflow"),
):
    PROVIDER_CAPABILITIES.setdefault(_variant, dict(PROVIDER_CAPABILITIES[_origin]))
_DS_OPENAI_LIKE: dict[str, object] = {
    "supports_response_format": True,
    "supports_streaming": True,
    "supports_tools": True,
    "supports_vision": False,
    "system_in_messages": True,
}
for _name, _extra in (
    ("xai", {"supports_vision": True}),
    ("cohere", {}),
    ("perplexity", {"supports_tools": False}),
    ("upstage", {}),
    ("hunyuan", {}),
    ("baichuan", {}),
    ("zai_global", {}),
    ("zhipu", {}),
    ("gemini", {"supports_vision": True}),
    ("fireworks", {"supports_vision": True}),
    ("deepinfra", {}),
    ("cerebras", {}),
    ("sambanova", {}),
    ("huggingface", {}),
    ("nebius", {}),
    ("vercel_ai_gateway", {"supports_vision": True}),
    ("github_models", {"supports_vision": True}),
):
    PROVIDER_CAPABILITIES.setdefault(_name, {**_DS_OPENAI_LIKE, **_extra})

'''

REASONING = '''

# --- DeepSteam 2026-10-15 providers: regional platforms reason like the original
_PROVIDER_THINKING_STYLES.update({
    "dashscope_intl": "enable_thinking",
    "dashscope_us": "enable_thinking",
    "minimax_cn": "reasoning_split",
})
_PROVIDER_REASONING_PATTERNS.update({
    "dashscope_intl": _PROVIDER_REASONING_PATTERNS["dashscope"],
    "dashscope_us": _PROVIDER_REASONING_PATTERNS["dashscope"],
})
'''

CONTEXT = '''

# --- DeepSteam 2026-10-15 providers: families that all ship >=128k windows, so
# an un-annotated entry is not squeezed into the 16k fallback.
KNOWN_LARGE_CONTEXT_MARKERS = KNOWN_LARGE_CONTEXT_MARKERS + (
    "glm-4", "glm-5", "minimax-m", "command-a", "sonar", "mistral-large", "mistral-medium",
)
'''


def edit(path: Path, anchor: str, replacement: str) -> str:
    text = path.read_text(encoding="utf-8")
    if MARK in text:
        return text
    count = text.count(anchor)
    if count != 1:
        raise SystemExit(f"{path}: anchor found {count} times")
    return text.replace(anchor, replacement)


def main() -> None:
    pkg = Path(sys.argv[1])
    check_only = "--check" in sys.argv
    reg = pkg / "services" / "provider_registry.py"
    caps = pkg / "services" / "llm" / "capabilities.py"
    reas = pkg / "services" / "llm" / "reasoning_params.py"
    ctx = pkg / "services" / "llm" / "context_window.py"

    out: dict[Path, str] = {}
    text = edit(reg, '    ),\n)\n\n\nNANOBOT_LLM_PROVIDERS', '    ),' + NEW_SPECS + ')\n\n\nNANOBOT_LLM_PROVIDERS')
    if MARK not in reg.read_text(encoding="utf-8"):
        anchor = '    "yapi": "y_api",\n}'
        if text.count(anchor) != 1:
            raise SystemExit("alias anchor missing")
        text = text.replace(anchor, '    "yapi": "y_api",\n' + NEW_ALIASES + '}')
    out[reg] = text
    out[caps] = edit(caps, '# Default capabilities for unknown providers', CAPS.lstrip('\n') + '# Default capabilities for unknown providers')
    for path, block in ((reas, REASONING), (ctx, CONTEXT)):
        current = path.read_text(encoding="utf-8")
        out[path] = current if MARK in current else current.rstrip('\n') + '\n' + block

    for path, text in out.items():
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as handle:
            handle.write(text)
        py_compile.compile(handle.name, doraise=True)
        Path(handle.name).unlink()
    if check_only:
        print("check ok:", ", ".join(p.name for p in out))
        return
    for path, text in out.items():
        if path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8", newline="")
            print("patched", path)
        else:
            print("unchanged", path)


if __name__ == "__main__":
    main()
