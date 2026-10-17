# DeepSteam r11 source update

Source version: `2026.10.17-r11-harness-core`.
Paired installed version: `2026.10.17-r11-harness-core-local`.
Current paired OpenMAIC build: `w_YlqwSMVFIPwGLN1gLy_`.

This publication incorporates the Harness migration and the subsequent October 17 experience fixes. It is based on the existing `standalone-2026-10-16` history. No new installer, desktop distribution ZIP, or removable-drive package is produced by this source update.

## Shared execution

All five interactive entry points use Harness for model/tool turns. Surface adapters retain teaching operations, route actual context and source references, freeze the selected model, map native sessions, and expose progress, questions, cancellation, completion, and structured failures. Ordinary file tasks no longer require a DeepTutor agent to delegate to a second general-purpose agent loop.

Document skills resolve the bundled Python/Node environment. Execution failures preserve useful diagnostics. Generated files must exist, be nonempty, and parse before becoming attachments; links survive recorded session recovery. MD, Word, PDF, XLSX, and PPTX were exercised with the actual configured model. Plugin and staged-repair lifecycle checks used deterministic decisions with real tools and files.

## Preserved standalone repairs

- Bilibili account/session integration, avatar/sign-out state, backend subtitles, local playback and timestamp/rate controls are retained. Bilibili and YouTube are the primary supported video targets; no claim of complete support for every domestic platform is made.
- Desktop transport, immersive reading, current launcher/installer source, and uninstall ownership/integrity handling remain included.
- Gold spiral icons, localized installation behavior, and retained user-data settings are preserved in the paired local installation. The public source keeps English defaults.

## Subsequent experience fixes

- Restore the public Harness pipeline result contract so Partner answers persist after streaming and reopening.
- Retain sidebar state within the correct workspace/account scope; reject stale responses after unmount, workspace change, or authentication invalidation.
- Resolve trusted persisted source IDs and publish verified original-image references through the existing immutable file service.
- Repair formula/table/diagram layout, classroom return navigation, video-export lifecycle, and trusted user-initiated fullscreen.
- Refill bounded classroom content prefetch before narration when the buffered result is already complete. At most two content jobs run concurrently; order, failure and cancellation remain enforced.

A same-source real-model classroom pair measured 659.803 s before and 593.053 s after, with nine versus six slide pages. This is one observation, with different generated outlines, not a stable speed guarantee. Sparse pages and occasional layout retries remain.

## Validation and remaining work

[Validation](docs/validation.md) records 15 real-model execution cases, 31 parsed artifacts and 22 successful downloads, plus follow-up experience tests. [Project status](docs/project-status.md) explicitly retains pending video-follow checks, task-board dragging, provider-dependent services, long-run performance, and remaining classroom layout issues.

The public-source manifest is regenerated from this publication. Older runtime verification reports in `installer/` are historical component checks, not proof of a new r11 installer. The local upgrade and rebuilt OpenMAIC have been tested; a complete clean-checkout native installer rebuild is still unproven. See [source provenance](docs/source-provenance.md).

For independent review, use this commit's source and [review guide](docs/review-guide.md). External Pro review was requested separately; its completion is not asserted by these release notes.
