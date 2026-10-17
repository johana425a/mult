# Source provenance and build coverage

## Publication base

Repository: <https://github.com/johana425a/mult>.

The update starts from `standalone-2026-10-16` at `05c1fbdfe9456837554c990f5244bcaf03fc6fc3`, retaining the existing public history. The former default-branch head was `23a40ba72fead32de009179278fd000f24dd2034` (r8 release title); some source metadata already referred to r9. Those stale labels are replaced with r11 metadata in this publication.

| Upstream component | Pinned base |
| --- | --- |
| DeepTutor v1.6.14 | `6cf793bd868ba5ecbe64722936d4be8fab5a01df` |
| OpenMAIC v1.1.2 | `1f05a70ac93e09c67fb4d3aafb9c2b068d14fcce` |
| DeepSeek Harness | `d743267388641bc76f17c45ce8b4c231aed1d32c` |

These are upstream bases, not claims that the modified trees match upstream byte-for-byte. Package lockfiles and runtime dependency manifests retain component-specific pins.

## Included source inputs

- r11 core review snapshot `DeepSteam-r11-Harness-Full-Source.zip`: SHA-256 `53ed2d0f1b516fb58434316c73d1f4535da539a8a38856d108430068d92e5b1c`.
- Subsequent experience source snapshot `DeepSteam-r11-Experience-Source-20261017.zip`: SHA-256 `ff25d64bad5d5a48d29e74b9b989e0c85beaa40602c5edcdaaf90812118f36cc`.
- Current installed integration, portal, desktop, backend and Harness source, compared with the latter snapshot at publication preparation.
- Current OpenMAIC source paired with build `w_YlqwSMVFIPwGLN1gLy_`, current renderer source, and launcher/installer helpers.
- Seven available native sidebar/auth source overlays applied to their canonical DeepTutor web paths; focused regression scripts made checkout-relative.

The review ZIP hashes identify input snapshots. They are **not** hashes of this edited GitHub publication. The final public bytes are described by `PUBLIC-SOURCE-MANIFEST.json`. Source paths are ASCII, public documentation is English, interface fallbacks are English, and text line endings are normalized for identical checked-out bytes. Saved language choices in the local application are unaffected.

Personal user data, browser profiles, model secrets, tokens, raw private review artifacts and retained conversation/source fixtures are excluded. Acceptance reports publish aggregate outcomes and timings, not private session identifiers or source content. Duplicate historical recovery trees are not copied into current canonical directories; earlier versions remain in Git history.

An obsolete machine-specific process-cleanup fixture is removed. Historical runtime
verification paths are made installation-relative and explicitly labeled historical.
Neither change runs cleanup or changes an installed application.

## Build coverage

The r11 local upgrade was applied as a verified program overlay and a rebuilt OpenMAIC runtime. The core integration, backend, current Harness modules, OpenMAIC source, renderer, desktop shell and available installer source are included here.

Some pre-r11 native frontend repairs were applied to compiled JavaScript, and the complete corresponding source has not been recovered and validated. The seven latest native source overlays improve coverage but do not close every earlier gap. **A full installer reconstructed solely from a clean checkout has not been demonstrated.** The existence of installer source and lockfiles must not be described as complete binary reproducibility.

Generated runtime dependencies, native libraries, parser model weights, built Next assets and installed payloads are not committed. Builders must stage licensed pinned dependencies, compile components, regenerate payload ownership/integrity manifests and test the exact resulting distribution. `installer/python-runtime-verification.json` is a retained historical component report; it is not a new full-build acceptance.

The r11 publication also corrects the Harness staging list to include the new execution-error, surface-tool, extension, repair and deployment-policy modules. Static import closure is checked before publication. This source-packaging correction does not modify a running installation.

## Reviewing this version

Use a fixed Git commit link to avoid reviewing changing branch contents. Begin with [architecture](architecture.md), [validation](validation.md), [project status](project-status.md), then inspect actual implementations and tests. External review requests are opinions to verify against code; this repository does not claim that a pending Pro review has approved the architecture.
