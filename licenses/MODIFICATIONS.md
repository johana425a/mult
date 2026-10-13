# DeepSteam modification notice

This is a modified integration of the pinned projects listed in `NOTICE.md`. Original license files, source ownership, and applicable third-party notices are retained.

## Integration changes

- `desktop/` adds the desktop shell, internal transport, managed startup and shutdown, storage migration, and uninstall entry point.
- `integration/` adds the Harness host, shared model gateway, account-connection workflow, workspace document tools, read queues, cached extraction, source references, and persistent reading progress.
- `portal/` associates materials, classrooms, and original answer records while preserving user-selected provider settings.
- `scripts/` supplies component lifecycle management, storage selection, document workers, and runtime verification.
- `installer/` stages compatible runtime assets and implements Windows installation, ownership-aware uninstall, progress reporting, and package validation.
- Modified DeepTutor frontend and backend files add DeepSteam branding, the unified model selector, classroom access, workspace integration, content management, task recovery, and usage recording. File-level notices identify modified files where applicable.
- Modified OpenMAIC files add shared model routing, document and image transfer, original-source retention, classroom storage integration, speech configuration, and desktop-compatible rendering.

## English public edition

The English public edition changes interface strings, prompts, comments, documentation, default locale settings, source examples, and machine-specific development paths. It uses English filenames and English default language settings. Generic internal transport remains an implementation detail inside the desktop application.

Non-runtime upstream agent notes, historical snapshots, documentation media, duplicate translated documentation, personal configuration, installed runtimes, model weights, logs, databases, and user records are excluded from the public export. Required code, English notices, and applicable licenses are preserved.

The source edition is distinct from previously produced binary packages. Its final file manifest is regenerated from the actual localized export, and no previous package hash is presented as a hash of an edited file.

## Document-tool notices

MinerU is integrated through an isolated document runtime and a structured worker. Added integration preserves original pages, asset references, extraction coverage, queue state, cache reuse, and recoverable workspace summaries. MinerU parsing code and document model artifacts retain their upstream attribution and licenses.

The MinerU license retains the complete official English additional terms and the Apache License 2.0 base text. Duplicate translated license text is omitted from this English edition. The preserved model registry reference has English comments and unchanged repository and artifact identifiers.

MinerU runs only as a local document tool. The worker loads the MinerU 4.0.12 Python library, the MinerU2.5-Pro-2605-1.2B GGUF weights and the ONNX small models from the installation folder, and serves the VLM through the official llama.cpp server on a loopback address with a one-time key. MinerU defaults to DeepSteam's `adaptive` tier: the small ONNX models parse each batch first and only pages whose layout shows tables or display formulas are parsed again with the `standard` tier's local VLM; results record the tier of every page and the VLM's measured token use. `standard`, `advanced` (local VLM with image analysis) and `basic` (no VLM) remain available on request. If an explicitly requested VLM tier cannot run, the worker reports an error instead of switching tiers or services; adaptive complex pages that cannot get the VLM keep the small-model result with a warning. The installer also places the official Vulkan build of the same llama.cpp release (b11541, `llama-b11541-bin-win-vulkan-x64.zip`, SHA-256 pinned) in `runtime/mineru/llama-server-vulkan`; the worker uses it only for a real GPU reported by that build and otherwise, or after a GPU failure, uses the CPU build. Khronos Vulkan-Headers notices (v1.4.357, the SDK of that release) are recorded with the llama.cpp dependency notices. The document queue runs MinerU in a separate parse lane with one persistent worker (models stay loaded), parses ahead of sequential reads, accepts background preparation of up to 50 documents and returns progress after a bounded wait. Modified DeepTutor files route their MinerU engine to this local worker and refuse the hosted MinerU API inside DeepSteam. Modified OpenMAIC files hide and reject hosted and remote MinerU providers and disable the MinerU cloud fallback.

These modifications do not claim that every document can be perfectly recognized, that a language-model login provides every auxiliary model service, or that deterministic test fixtures establish live teaching quality.
