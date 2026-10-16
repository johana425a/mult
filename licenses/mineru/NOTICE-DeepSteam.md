# MinerU document tool in DeepSteam

MinerU 4.0.12, upstream OpenDataLab / MinerU Team, commit
`b7f3dd0c5f6e6d66a298239ffd02b328b873918e`, provides the local document parser.
The application code is distributed under the attached MinerU Open Source
License (Apache License 2.0 with additional terms), not plain Apache-2.0.
This notice and the accompanying licenses are included with the binary runtime.

DeepSteam's 2026-10-12 modifications consist of an isolated portable runtime,
an offline JSON worker, task/result integration, page and asset preservation,
packaging manifests, and synthetic acceptance checks. Upstream parsing code is
not relabeled as DeepSteam-authored. The parser is a document tool and is not
a conversational model provider.

## Model artifacts

The ONNX bundle is `opendatalab/MinerU-4_models_onnx` at
`358310b4f64b95f9fefc372ad899356e4111f376`. Its original model licenses continue
to apply. The included upstream manifest identifies the model-specific source
repositories and hashes. Layout and OCR sources are PaddlePaddle; formula,
stamp and table artifacts also trace through the Apache-2.0-declared OpenDataLab
Torch model bundle. That bundle does not describe the earlier UNet weight
conversion lineage; no claim of a complete training-data/author audit is made.

The default GGUF and mmproj artifacts are the exact files selected by upstream
MinerU's pinned registry, from `jinzhenj/MinerU2.5-Pro-2605-1.2B-GGUF` revision
`9185688a0495e1577d521a757c7c0b62dd38ca48`. Both files declare
`general.license = apache-2.0` in their GGUF metadata. Their model name is
`MinerU2.5 Pro 2605 1.2B`. The original OpenDataLab Pro-2605 model card declares
Apache-2.0 and is included for attribution. Qwen and the original model authors
retain the acknowledgements in that card.

The GGUF repository provides no separate model card or conversion revision.
We do not claim it is published under an OpenDataLab account, that it supplies
a particular original-weight revision, or that DeepSteam reproduced its
quantization. Source URLs, fixed repository revision, exact byte counts and
full-file SHA-256 checks are retained in the included provenance manifests.

## Native inference dependency

The distributed native engine is official `ggml-org/llama.cpp` b11541,
commit `f2918cabbffe8abf8e2a90c1c089085fa116c2cf`, Windows CPU release.
Its MIT license, LLVM OpenMP license, and pinned dependency notices are included.
The archive SHA-256 is
`cdc0535d11038bb337dfba3c15682050eaa9c07aedd0f915b4c09e8a8e8c0a5c`.
The worker uses MinerU's supported HTTP client with a private local subprocess;
the model weights remain offline and are not registered as a chat provider.

Upstream's `mineru-llama-cpp` 0.1.3 Python wrapper was investigated but is
excluded from this distribution because a separate wrapper license was not
verified. It is not assigned the license of either llama.cpp or MinerU.

## Redistribution

Preserve this notice, the accompanying license texts, relevant upstream model
cards, and dependency license files when redistributing. Online service use has
the additional attribution requirement described in MinerU-LICENSE.md; its
wording allows the relevant interface or prominent public documentation.
This file does not replace the actual license terms.
