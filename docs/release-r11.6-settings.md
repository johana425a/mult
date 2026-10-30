# r11.6 settings repair packaging

Version: `2026.10.19-r11.6-settings`.

This is the user-requested packaging of the completed `r11.5-settings-fix1`
program changes. The user explicitly requested no additional tests for this
handoff. It is not a release-gate promotion or new full acceptance result.

Included changes cover independently saved theme and language preferences,
Chinese settings navigation, provider setup choices, removal of the requested
about-navigation entry with licenses retained, installer/uninstaller styling
and layout, per-stage percentage progress, the desktop uninstall entry and
diagnostics, and bounded external rollback snapshots for large ownership
manifests. Previously integrated model, classroom, learning and scroll fixes
remain in the runtime. The original reported uninstall path mismatch was not
reproduced; improved diagnostics are not proof that every uninstall scenario
is resolved.

Only release metadata and the packaging exclusion for the extensionless
installed-ownership manifest were changed after the recorded repair checks.
The compiled frontend and classroom are reused without a functional rebuild.
Source defaults remain English; the Windows distribution uses Chinese defaults.

The handoff only checks archive and file integrity. It does not run the
installer, launch or restart the original client, exercise live model services,
or claim a cold installation on another computer. User credentials, personal
documents, learning records, browser profiles and installed-ownership state
must not enter the distributable. Source and dependency notices are retained.
