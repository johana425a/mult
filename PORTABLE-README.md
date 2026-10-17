# DeepSteam source and portable distribution

Current source version: `2026.10.17-r11-harness-core`.

The GitHub **Download ZIP** button downloads source code. It does not produce a
ready-to-run portable application and does not include Python/Node runtimes,
native dependencies, built frontend assets or optional document model weights.

A separately packaged Windows distribution must include its matching installer,
payload and dependency notices. Its bundled runtime can avoid requiring a separate
Python/Node installation, but users still configure their own model connection.
Application and platform credentials are never copied from the publisher.

The root portable setup/start/stop helpers are retained source for a fully staged
distribution. Do not run them expecting a plain source checkout to become a complete
installation. Runtime dependency links and integrity manifests must be regenerated
from the actual payload; historical file/link counts are not current guarantees.

This update publishes source and records only. It does not replace previously
distributed installer/portable archives. See [release notes](RELEASE.md),
[user/source guide](GUIDE.md), [validation](docs/validation.md), and
[build coverage](docs/source-provenance.md) before building or sharing a binary.

Keep user-selected accounts, documents, workspaces, chat history and learning
records outside a public program payload. Use the installer-owned upgrade and
uninstall flows for an installed copy, preserving user data unless its owner
explicitly selects removal.
