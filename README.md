# DeepSteam

DeepSteam brings document reading, personalized learning, video study, workspace tools, and interactive classrooms into one desktop application. Chat, personalized learning, immersive reading, the OpenMAIC workbench, and classroom dialogue now submit interactive turns to **one Harness execution core**. DeepTutor and OpenMAIC continue to provide their interfaces and teaching services.

**Current source snapshot: `2026.10.17-r11.1-review`, including the October 17 experience fixes and architecture-review repairs.** Existing Git history and upstream licenses are preserved. The [review disposition](docs/review-remediation.md) distinguishes fixed defects, actual tests and remaining reproducibility limits.

| Start here | Contents |
| --- | --- |
| [Release notes](RELEASE.md) | Changes since the previous public snapshot and known limits |
| [Architecture](docs/architecture.md) | Five entry points, shared execution, tools, model and persistence contracts |
| [Validation](docs/validation.md) | Real model results, timings, deterministic checks, and untested areas |
| [Project status](docs/project-status.md) | Resolved and outstanding experience issues |
| [Source provenance](docs/source-provenance.md) | Upstream pins, source inputs, public normalization, and build coverage |
| [Review guide](docs/review-guide.md) | Code entry points and questions for independent architecture review |
| [Review remediation](docs/review-remediation.md) | All 18 review items, follow-up runtime defects and validation boundaries |
| [User and source guide](GUIDE.md) | Configuration, usage, and component setup |

## What changed in r11

- Shared Harness execution for all five interactive surfaces, with stable session mapping, a frozen model selection per turn, cancellation, recovery, and structured failure details.
- Real MD, Word, PDF, Excel, and PowerPoint creation through the bundled execution environment; verified files become preview/download attachments. Learning summaries, chat archives, and mastery state remain distinct records.
- Backend subtitle access with source identity and timestamps, so a document task can read the whole transcript instead of only the visible subtitle rows. Bilibili and YouTube remain the primary video targets.
- Managed extensions and reversible program repairs, with dependency/version records and isolated lifecycle validation.
- Follow-up fixes for persisted answers, original-source links, classroom layout and video export, sidebar continuity, and bounded classroom content prefetch.

The earlier [execution acceptance](docs/validation.md) recorded 15 real-model cases, 31 parsed files and 22 downloads. The new [r11.1 review acceptance](reports/r11/review-acceptance.json) records 10 additional real-model turns, including initial failures and their repairs, 23 verified downloads, restart persistence and 56 focused regression passes. These are separate evidence sets. Tool registration is not treated as proof that every tool action works.

## Source and application distribution

This repository is a **source snapshot**, not a newly built Windows installer. It contains modified upstream code, integration code, current available repair source, dependency lockfiles, regression tests, and sanitized reports. Runtime binaries, model weights, credentials, browser sessions, textbooks, personal conversations, and learning databases are excluded.

The local installed r11 upgrade was an overlay plus a rebuilt OpenMAIC runtime. Some older native frontend fixes exist only as compiled patches or partial recovered source. A complete clean-checkout installer rebuild has **not** been established; see [build coverage](docs/source-provenance.md#build-coverage). Do not treat a GitHub source ZIP as an installable package or a claim of complete binary reproducibility.

The public source defaults to English; existing localized installations keep their saved settings. Regional settings are resolved at runtime. Each installation needs its own model connection. No personal account or conversational model weights are supplied here.

Run `python scripts/verify_public_source.py` to verify the reviewed files against [PUBLIC-SOURCE-MANIFEST.json](PUBLIC-SOURCE-MANIFEST.json). The check does not access a user credential store or contact a model provider. See [tests/r11/README.md](tests/r11/README.md) for focused regressions.

## Source layout

| Directory | Role |
| --- | --- |
| `desktop/` | Electron shell, internal transport, startup and lifecycle |
| `integration/` | Request adapters, shared model routing, Harness host, execution and document services |
| `portal/` | Authenticated internal APIs for materials, classrooms, records and files |
| `scripts/` | Runtime startup, storage, document workers and repair helpers |
| `installer/` | Windows installation, uninstall, launcher and packaging source |
| `upstream/DeepTutor/` | Modified learning interface and teaching services |
| `upstream/OpenMAIC/` | Modified classroom application, generation packages and renderer |
| `upstream/DeepSeekHarness/` | Pinned official execution framework source |
| `tests/r11/`, `reports/r11/` | Portable regression entry points and sanitized acceptance records |
| `licenses/` | Original licenses, attribution and modification notices |

## Upstream projects and licenses

DeepSteam integrates [DeepTutor](https://github.com/HKUDS/DeepTutor), [OpenMAIC](https://github.com/THU-MAIC/OpenMAIC), and [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness). Optional local document parsing uses [MinerU](https://github.com/opendatalab/MinerU) and an official [llama.cpp](https://github.com/ggml-org/llama.cpp) runtime.

MinerU includes additional terms beyond Apache License 2.0, including attribution and commercial-use thresholds. Read [its license](licenses/mineru/MinerU-LICENSE.md), [distribution notices](licenses/NOTICE.md), and [modification notices](licenses/MODIFICATIONS.md) before redistribution. Original ownership and licenses remain applicable; DeepSteam branding does not imply upstream endorsement.

Development and examples were assisted by coding agents. Deterministic fixtures, actual model output, operator observations, and user learning outcomes are separate evidence categories. Private configuration and user records must never be committed.
