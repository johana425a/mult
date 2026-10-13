# DeepSteam English public source edition

Base application version: `2026.10.13-r8-adaptive-vlm`.

## Changes in r8 (from `2026.10.12-r7-harness-tools`)

- Document reading: placeholder and damaged cursors no longer cause "pagination position is invalid"; every result carries an integer `next_start_unit` fallback.
- MinerU runs only on this computer. The default `adaptive` tier uses the small models first and the local MinerU2.5 VLM only for pages with tables or display formulas; results record the tier of every page and the VLM's measured token use.
- MinerU runs in its own lane with one persistent worker, read-ahead, background preparation of up to 50 documents and bounded waits, so reading other files never waits behind a parse.
- The VLM runs on a GPU through the official Vulkan build of the same llama.cpp release when one is present, and on the CPU build otherwise.
- Word/PowerPoint embedded images and image files are parsed by local MinerU.
- Workspace access levels (Full computer by default, Workspace only on request) with switches on the Workspace agent page and the chat composer.
- iOS-style motion across DeepTutor, OpenMAIC, the startup page and the installer.

This revision is source only: no installer has been built from it yet. `native_build_id` and `openmaic_next_build_id` in `RELEASE-IDENTITY.json` still describe the r7 binary build.

This edition publishes English source, configuration templates, integration code, and required notices. It excludes installed runtime binaries, document-tool model weights, personal data, credentials, machine-specific settings, and historical Git metadata. English is the default application language; local regional settings are detected at runtime without a fixed personal timezone.

The base revision removes the bundled conversational model and exposes user-configured model connections. MinerU remains a document tool with its own runtime and model requirements. Document extraction retains source references, page images, queue state, cached results, and recoverable workspace progress.

The English source export changes documentation, user-facing text, default locale settings, examples, and machine-specific development paths. It is a separate public-source edition, not an assertion that the earlier binary package already contains these English changes. Final build and runtime verification applies to the artifacts actually produced from this tree.

Pinned upstream versions are recorded in `RELEASE-IDENTITY.json`. Applicable terms and source attribution are in `licenses/`. The public manifest is regenerated after localization; hashes from an earlier binary package are not reused as hashes of this edited source tree.
