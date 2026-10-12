# DeepSteam English public source edition

Base application version: `2026.10.12-r7-harness-tools`.

This edition publishes English source, configuration templates, integration code, and required notices. It excludes installed runtime binaries, document-tool model weights, personal data, credentials, machine-specific settings, and historical Git metadata. English is the default application language; local regional settings are detected at runtime without a fixed personal timezone.

The base revision removes the bundled conversational model and exposes user-configured model connections. MinerU remains a document tool with its own runtime and model requirements. Document extraction retains source references, page images, queue state, cached results, and recoverable workspace progress.

The English source export changes documentation, user-facing text, default locale settings, examples, and machine-specific development paths. It is a separate public-source edition, not an assertion that the earlier binary package already contains these English changes. Final build and runtime verification applies to the artifacts actually produced from this tree.

Pinned upstream versions are recorded in `RELEASE-IDENTITY.json`. Applicable terms and source attribution are in `licenses/`. The public manifest is regenerated after localization; hashes from an earlier binary package are not reused as hashes of this edited source tree.
