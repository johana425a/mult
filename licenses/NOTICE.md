# DeepSteam distribution notices

DeepSteam integrates and modifies existing open-source software. The original projects and their licenses remain applicable. The DeepSteam name does not claim that upstream capabilities were independently invented or that upstream organizations endorse this distribution.

## Primary components

- **DeepTutor v1.6.14**, commit `6cf793bd868ba5ecbe64722936d4be8fab5a01df`: Apache License 2.0. Copyright 2025 Data Intelligence Lab, The University of Hong Kong. Source: <https://github.com/HKUDS/DeepTutor>. License: `DeepTutor-LICENSE.txt`; dependency notices: `DeepTutor-THIRD_PARTY_NOTICES.md`.
- **OpenMAIC v1.1.2**, commit `1f05a70ac93e09c67fb4d3aafb9c2b068d14fcce`: MIT License. Copyright (c) 2026 THU-MAIC. Source: <https://github.com/THU-MAIC/OpenMAIC>. License: `OpenMAIC-LICENSE.txt`.
- **DeepSeek Harness**, commit `d743267388641bc76f17c45ce8b4c231aed1d32c`: MIT License. Source: <https://github.com/deepseek-ai/deepseek-harness>. License: `harness-MIT.txt`.
- **MinerU 4.0.12**, commit `b7f3dd0c5f6e6d66a298239ffd02b328b873918e`: Apache License 2.0 with additional terms. Copyright 2026 MinerU Team. Source: <https://github.com/opendatalab/MinerU>. License and source records: `mineru/`.

## MinerU attribution

**DeepSteam uses MinerU for document parsing.** MinerU is an AI-callable document tool, not a conversational model provider. Its license includes commercial-use thresholds, an online-service attribution obligation, definitions, and termination provisions. The full official English additional terms are preserved in `mineru/MinerU-LICENSE.md`; the Apache base license is in `mineru/Apache-2.0.txt`. This prominent public notice provides attribution and does not replace the actual license terms.

Document model artifacts retain their own licenses. The pinned ONNX and GGUF source manifests, original model card, GGUF embedded-license evidence, and associated notices are in `mineru/`. A source checkout does not include these model weights. The official llama.cpp Windows CPU engine is a separate native document-tool dependency under MIT; its license, LLVM OpenMP license, and dependency notices are preserved here. An unverified third-party Python wrapper is not included.

## Modifications

DeepSteam adds a desktop shell, shared model routing, folder workspaces, material and classroom integration, document queue and recovery, source-image references, content management, usage tracking, and Windows lifecycle management. The English public edition localizes interface text, comments, documentation, and defaults, and removes private-machine configuration and non-runtime demonstration material. See `MODIFICATIONS.md`.

The official English part of the bilingual MinerU license is retained without changing its terms. The duplicated translated section is omitted in this English edition. Comments in `mineru/model-registry.py.txt` are translated to English; repository identifiers and artifact paths are preserved. Pinned provenance records describe the original upstream artifacts. They are not represented as hashes of subsequently localized source files; the final public file manifest records exported-file hashes.

## Native image dependencies and tokenizer assets

The Windows runtime can include unchanged `libvips-42.dll` and `libvips-cpp-8.18.6.dll` from `@img/sharp-win32-x64@0.35.4`, declared Apache-2.0 AND LGPL-3.0-or-later. Copyright notices, complete licenses, corresponding source/build links, and replacement information are retained in `sharp-libvips/`. The libraries remain separate replaceable DLLs.

Public tokenizer tables may be staged for offline tiktoken initialization. The tiktoken MIT license, GPT-2 source license, public source URLs, and fixed hashes are retained in `tiktoken/`. These vocabulary assets are not credentials or account access. Runtime binaries and downloaded assets are excluded from this public source tree.

## AI assistance and records

Development and prepared examples were assisted by Codex. Prepared examples, deterministic test fixtures, actual model responses, and student answers must be distinguished. Passing an integration test does not establish model answer quality or student mastery.

Preserve applicable copyright, license, attribution, and modification notices when redistributing. Additional dependencies remain governed by their own licenses.
