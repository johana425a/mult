# Historical standalone patches

This directory preserves the available October 15-16 patch sources from the
previous standalone branch. Current canonical implementations and r11 status are
documented in [source provenance](../docs/source-provenance.md) and
[project status](../docs/project-status.md). These files are historical repair
inputs, not a prescription to apply every old patch to the current release.

Some earlier native UI changes targeted compiled Next.js chunks because their
matching source was unavailable. The repair process copied a build, checked
unique anchors and syntax, renamed changed chunks and references, then changed
the runtime build pointer while retaining the previous build for rollback.
That gap is still relevant to full source reproducibility.

| Historical folder | Original purpose |
| --- | --- |
| `20261015-sidebar-workspace/` | Add workspace folder selection to the sidebar |
| `20261015-ui-refresh/` | Colors, typography, panels, focus states and provider icons |
| `20261015-providers/` | Additional provider descriptors and runtime locale detection |
| `20261016-installer-mark/` | Earlier installed-program registration helper |

The r11 Harness host now supports authorized application-code access and staged,
verified, reversible repairs; the older blanket statement that it cannot modify
the application is no longer the current architecture. Credential and ownership
boundaries still apply. Never replay a historical compiled patch into a different
build without verifying its exact anchors and retaining a rollback copy.

Use the current installer and its ownership-aware registration/uninstall workflow
for a new distribution. Old patch records do not establish that a clean source
checkout reproduces the complete installed application.
