# Document-capable Windows release

Use `installer/build_document_release.py` for new releases. `build_installer.py`
is the retired r3 entry point; it refuses a new build before copying any files.
The original portable-Python freeze is historical. The document closure is pinned
in `document-runtime-requirements.txt`, and accepted OCR wheel files come from
`reports/workspace-document-ocr-dependencies.json`.

## Freeze, validate, build

Run with the private Python using `-I -B`. All paths below are relative to the
project. Pick a new artifact/version. Prepare only after the final app builds,
uninstaller tests and current software acceptance are complete.

```text
installer/build_document_release.py prepare
  --version 2026.10.12-r6.3-documents
  --artifact r6.3-documents-20261012
  --baseline installer/r6.2-documents-20261012/release/DeepSteam-Setup-2026.10.12-r6.2-documents-x64.payload.dat
  --baseline-sha256 74e8e6a5f1dc68a9508ca6da3f068fb6d28d7c407fdf1928d3fb08dd06f05b3f
  --program-manifest reports/FINAL-PROGRAM-MANIFEST.json
  --program-manifest reports/FINAL-ADDITIONAL-PROGRAM-MANIFEST.json
  --component-manifest reports/harness-runtime-files.json
  --component-manifest reports/mineru-licensed-runtime-files-20261012.json
  --native-receipt reports/FINAL-NATIVE-RECEIPT.json
  --acceptance reports/FINAL-SOFTWARE-ACCEPTANCE.json
  --uninstaller-report installer/FINAL-UNINSTALLER-BUILD/build-report.json
  --extra-share-file installer/REVIEWED-REPAIR-DIRECTORY/DeepSteam-REPAIR.zip
```

Manifest entries use `source`, `target` (or `path`), `bytes`, `sha256`. Later
manifests replace earlier deltas. Supply complete final native and OpenMAIC
inventories; other program files are incremental. If package dependencies changed,
also supply `--junctions` with the reviewed complete contained-link manifest.
This entry point preserves pre-existing artifacts and does not deploy or write E.

For the Harness document-tool release, the MinerU component must attest to
`redistribution_status: verified`, version 4.0.12 and `tool_only: true`. Its offline
acceptance must match the exact worker SHA. The Standard tier uses a fixed official
MIT-licensed llama.cpp server; do not include the unlicensed `mineru-llama-cpp`
Python wrapper. The Basic and Standard document weights are tool assets and are
not available as chat models. The retired bundled Qwen files are excluded by
`retired_components.py`; user-added providers and models are not covered by that
retirement list.

Pass complete compiled frontend inventories and immutable Harness/MinerU runtime
closure inventories. Filenames such as `sessions` or `credentials` can occur in
compiled routes and SDK source; only the approved compiled/dependency code roots
permit those names. Account-state leaves, databases, browser profiles and `.env`
files remain excluded in every root.

Preparation prints the frozen spec hash. Pass that exact hash to `validate`, then
`build`, together with the same `--version` and `--artifact` arguments:

```text
installer/build_document_release.py validate --version VERSION --artifact ARTIFACT --spec-sha256 HASH
installer/build_document_release.py build --version VERSION --artifact ARTIFACT --spec-sha256 HASH
installer/build_document_release.py share --version VERSION --artifact ARTIFACT --spec-sha256 HASH
```

The uninstaller build report must attest to the current root source via
`source_sha256` and either `tests.passed: true` or a nonempty all-passed test list
with positive `checks` matching `total_checks`. The package creates the launcher from
that reviewed source with the new release version; it does not reuse a stale EXE.
`share` requires the final package acceptance, verifies its frozen inputs, and
creates six distribution files including source/license companions. It writes D
only. A separate explicit publishing step is needed for the removable drive.
Optional `--extra-share-file` ZIPs are frozen by SHA, checked, included beside the
installer, and added to the final checksum manifest (for example, a seventh file
containing the standalone old-version uninstall-entry repair).

## Required release gates

- Validate every fixed OCR file, its configuration and three bundled model files.
- Require the exact PDF, DOCX, PPTX, XLSX and OCR package versions; reject duplicate
  installed versions and divergent Host source/runtime copies.
- Reuse unchanged compressed public payload records. No user database, account,
  private document or installed-user-state directory is a build input.
- Verify every final payload file SHA, ZIP CRC, and actual Windows installer self-test.
- Extract only the final package's document Python closure (about 348 MB, not the
  app/model payload) to a fresh temporary folder and run its own Python with
  `-I -B` and a minimal environment.
- Import the real native libraries; read generated PDF text and English
  scanned pages, Word text/table/image, PowerPoint, spreadsheet formula strings,
  Markdown, and the original PDF page image. All network calls are blocked and
  model calls are absent. The synthetic English scan ships with the probe so it
  does not depend on an additional language font on the recipient's computer.
- Remove that new test folder. Failure prevents a successful build report. This
  does not retry or remove any prior cleanup-blocked folders.

The archive includes `installer/document-runtime-lock.json`, the self-check and
the synthetic fixture. On a recipient computer the same check can run directly:

```text
runtime/python/python.exe -I -B scripts/check_document_runtime.py
```

The check neither launches the UI nor reads user files. A passed parser check does
not imply perfect semantic interpretation of formulas, graphics or arbitrary scan
quality. Source visuals and incomplete/uncertain statuses must remain visible.
This package-level test is not a claim of a complete second-physical-PC UI install
or cloud-model acceptance; those are separate release evidence.
