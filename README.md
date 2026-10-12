# DeepSteam

DeepSteam is a desktop education assistant that combines document reading, guided learning, workspace tools, and interactive classrooms in one application.

This repository contains the English public source edition of `2026.10.12-r7-harness-tools`. It includes modified upstream source and DeepSteam integration code. It does not include an installed application, private documents, personal learning records, saved accounts, API credentials, or machine-specific runtime configuration.

## What it provides

- A unified model catalog for chat, learning plans, books, workspace assistance, and classroom generation.
- User-controlled account authorization and API connections. Passwords and authorization tokens stay outside conversational context.
- Folder-based workspaces with shared document reading across application features.
- A durable document queue, reusable extraction results, original-page and image references, and recoverable multi-file reading progress.
- PDF, DOCX, PPTX, spreadsheet, Markdown, and text ingestion. MinerU is available as a document tool rather than a chat model.
- Interactive classroom creation, source-material references, local speech options, and video export integration.
- Content management, model-use records, installation lifecycle management, and an explicit uninstall entry point.

The public edition defaults to English and detects local regional settings at runtime. No personal timezone is fixed in the source. Each user selects their own models, storage location, credentials, and regional preferences. It has no preconfigured cloud account or bundled conversational model.

## Getting started

For a complete Windows distribution, keep its installer and matching payload file together, then run the installer. The desktop application manages its internal services; users do not need to enter an internal network address.

This repository is source code. A source checkout requires the component dependencies and compatible runtime assets before it can be packaged. See [GUIDE.md](GUIDE.md) for the source layout, setup workflow, and operating notes. Runtime binaries and document-tool model weights are downloaded separately from their pinned official sources and are excluded from this repository.

## Project layout

| Directory | Purpose |
| --- | --- |
| `desktop/` | Desktop shell, startup lifecycle, transport, and application integration |
| `integration/` | Harness host, model routing, document reading, and shared tooling |
| `portal/` | Material, classroom, and learning-record bridge |
| `scripts/` | Component startup, storage selection, document workers, and maintenance |
| `installer/` | Windows installer, uninstall logic, staging, and package verification |
| `upstream/DeepTutor/` | Modified learning application source |
| `upstream/OpenMAIC/` | Modified classroom application source |
| `upstream/DeepSeekHarness/` | Pinned Harness source |
| `licenses/` | Applicable licenses, source attribution, and modification notices |

## Open-source components

DeepSteam uses [DeepTutor](https://github.com/HKUDS/DeepTutor), [OpenMAIC](https://github.com/THU-MAIC/OpenMAIC), and [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness). The document-tool integration uses [MinerU](https://github.com/opendatalab/MinerU) and an official [llama.cpp](https://github.com/ggml-org/llama.cpp) runtime.

**MinerU is used for document parsing. Its license includes additional terms beyond Apache License 2.0, including attribution and commercial-use thresholds.** Read [the MinerU license](licenses/mineru/MinerU-LICENSE.md), [distribution notices](licenses/NOTICE.md), and [the modification notice](licenses/MODIFICATIONS.md) before redistribution. Upstream code keeps its original ownership and applicable licenses; the DeepSteam name does not imply upstream endorsement.

Development and examples were assisted by Codex. Prepared examples, deterministic test responses, actual model responses, and user answers are distinct kinds of evidence.

## Reliability and data

Reading tasks keep source identities, extraction status, original images, and progress records. The application can queue concurrent requests and resume persisted work. Document recognition still depends on source quality and parser capabilities; original pages remain available for checking formulas, scans, and diagrams.

Cloud calls use the model and service selected by the user. Language models, document parsing, embeddings, speech, and image generation have separate capability requirements. A successful language-model connection does not provide every other service.

Do not commit runtime data, credential files, private configuration, logs, or browser profiles. The public-source export contains no previous Git history from a personal installation.
