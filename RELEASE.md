# DeepSteam r9: selected-model vision and Harness capabilities

Version: `2026.10.13-r9-selected-model-vision`.
Previous distribution: `2026.10.13-r8-adaptive-vlm`.

## Document reading changes

- Text PDF, Word and PowerPoint extraction remains local and does not start a VLM.
- Scans, screenshots and embedded pictures retain original pixels for the current
  selected model. There is no separate implicit vision model or forced OCR step.
- Local MinerU is disabled by default. Only a user-owned advanced setting enables
  it; explicit model tool arguments cannot override that setting. Existing parser
  caches and reading state remain available, with disabled queues paused.
- Image input is gated by real connection verification, independent of a catalog
  support flag and without a DeepSeek-only model allowlist. Verification uses a
  small synthetic image only after the user confirms the request. Changed
  connection identity invalidates stale verification.
- Classroom and native learning ingestion retain image-only material, source
  positions and pending visual coverage. Complete text extraction is not recorded
  as complete understanding of the original document.

## Workspace and model changes

- Load official pinned Harness web fetch/search, interactive questions, plan mode,
  presented files and real workspace changes. Search requires a compatible
  selected DeepSeek connection; ordinary public-page fetch remains distinct.
- Questions persist and await actual user answers or cancellation. Plan mode
  blocks mutating execution tools until an actual user action leaves that mode.
- Declared deliverables support authenticated preview/download. File changes use
  actual diffs, with pending interaction and change state retained after restart.
- Default reasoning is High when the selected model supports that value and no
  explicit value was saved. Unsupported models keep native behavior. Existing
  explicit choices remain unchanged.
- Models remain frozen per request. Tool, image, streaming, context and usage
  metadata refer to the actual selection rather than a local-model fallback.

## Distribution and validation

The D-drive update replaces program files only. User data remains in its selected
data directory. The E-drive distribution contains the matching installer,
program payload, public source, required licenses and checksums; it excludes user
databases, accounts, credentials and private source materials.

`RELEASE-IDENTITY.json` records the component pins and final build IDs.
`BUILD-INFO.json` and the package manifests describe the exact shipped artifacts.
Fixture tests cover routing, image verification, parsing policy, interactive tool
state, source images, recovery and API boundaries without paid model generation.
They are software checks, not claims that every cloud model or another physical
computer was tested. The current host's startup checks and installer self-test
are recorded separately by the release workflow.

The public source defaults to English. This local distribution keeps the Chinese
interface and current DeepSteam dark/orange design. Upstream licenses and real
technical attribution remain under `licenses/`; product-facing branding stays
DeepSteam.
