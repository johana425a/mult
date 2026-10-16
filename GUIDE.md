# DeepSteam user and source guide

## Open and connect

Keep the installer executable beside its matching payload. Run the installer,
choose a local installation directory, and open DeepSteam from its shortcut.
The desktop manages its internal services; ordinary use does not require a
browser address or configuring a local network interface.

Use **Connect model** to authorize a supported account or add an API connection.
Complete account authorization on the provider's official page. Enter API secrets
only in the dedicated secure input. Learning, classroom generation and the
workspace agent resolve the selected model from the unified model catalog.
Individual task choices remain available. Supported models default to **High**
reasoning when no explicit choice was saved; an existing choice remains in effect.
Models without that setting retain their native behavior.

## Read documents and original images

Text PDFs, Word and PowerPoint files are read locally from their text layers.
Reading text does not start a visual language model or upload the original file.
The reader returns page, slide and picture references, plus a continuation cursor
when the selected scope is incomplete.

Scanned pages, screenshots, image files and embedded Office pictures retain their
original pixels. The agent reads those images with **the model selected for that
task**. It does not require an OCR-to-text conversion first, does not choose a
different vision model in the background, and does not silently discard images.
Sending an image uses the selected provider's connection and quota. Selecting a
text model does not make its image capability available.

A catalog's image-support flag is not proof that the configured endpoint accepts
images. Use the image verification action to send a small synthetic test image;
the application asks for confirmation before that test. Verification is tied to
the actual connection identity. Changed settings invalidate stale verification.
If image input is unsupported or unverified, the application says so and asks for
a supported model. No other provider is contacted automatically.

Source coverage remains separate from visual interpretation: enumerating all
pages or extracting all text does not mean the model has understood the images.
Retained picture references and pending visual coverage stay visible. Large scopes
must be read in complete bounded windows; sources are never silently truncated to
fit a smaller model.

Local MinerU remains an optional advanced parser, disabled by default. It is not
required for normal selected-model image reading. Only a user setting can enable
its local queue; a model tool argument cannot grant that permission. Disabling it
pauses queued parsing without deleting original files, previous caches or reading
progress. Existing local parser assets remain available where installed. Device
and speed information is measured locally, not a guarantee for another computer.

## Workspace agent capabilities

Open a folder from the workspace selector. Removing its workspace entry does not
recursively delete the computer folder. **Workspace only** restricts file tools to
that folder; **Full computer** allows other folders and drives. Credential stores,
browser profiles and DeepSteam's own private settings remain protected.

The workspace agent loads the pinned official Harness capabilities for web
access, questions, planning, presenting files and tracking changes:

- Web fetch reads public HTTP pages. Local/private network targets are rejected.
  Proxy routes whose destinations cannot be securely verified are also rejected;
  this restriction does not change the language model's global proxy settings.
  Official DeepSeek search requires an eligible selected DeepSeek connection and
  can consume that connection's quota. An unavailable search connection is shown
  as requiring configuration; it does not trigger an unrelated provider.
- Questions wait for a real user answer, free-text response or cancellation.
  The interface does not invent an answer on the user's behalf.
- Plan mode permits inspection and planning while execution tools stay read-only.
  Switching back to execution requires the actual user action.
- Presented files can be previewed or downloaded from a declared output. Generated
  HTML is isolated as untrusted content. File changes show actual differences,
  rather than a model-written claim about which files changed.

These capabilities use the selected model's supported tools and the application's
existing access controls. Loading a tool does not bypass account permissions.

## Learning, records and close

The application continues persisted conversations, learning records, documents
and tasks after restart. Closing stops only the services it owns. Model switching
affects the next request and does not relabel earlier replies or running tasks.
Classroom generation receives original selected source pictures with the same
frozen model selection. Speech, embeddings and image generation are separate
services with their own settings and capabilities.

## Export, backup and uninstall

Exported learning records exclude model credentials. A private data backup, if
wanted, belongs in a separate location and should be made while the application
is closed. Public source and share packages contain no learning database or saved
credentials. Some provider credentials are bound to the operating-system user
and must be entered again after migration.

Use the uninstall entry in settings or its installed shortcut. It checks program
ownership, preserves user data unless deletion was selected, and never recursively
deletes arbitrary workspace folders.

## Build and redistribute

Use compatible Python and Node.js runtimes, locked component dependencies, and
the upstream pins in `RELEASE-IDENTITY.json`. Stage optional licensed parser assets
through the document-runtime helpers; large runtime assets are not source files.
Build the components, regenerate program/source manifests, and test the exact
installer artifacts. Paths must remain installation-relative or user-selected.
The public source defaults to English; the local Chinese distribution retains
its Chinese interface.

Keep licenses, copyright notices and modification notes with redistributed code
and runtimes. See `licenses/` for upstream terms, including the additional MinerU
conditions. Prepared examples and deterministic fixtures are not proof of live
model output or user learning outcomes.
