# DeepSteam r11.6.8 settings source update

Source version: `2026.10.19-r11.6-settings`.
Package label: `r11.6.8`.
Source base: public commit `1e3e6cacb037100a53262e9521c2b87f76ca2b4b`.

This snapshot brings the public tree up to the October 19 r11.6 settings build
and includes the subsequent local repairs:

- Archived-workspace cleanup: reading materials, reading collections and books
  can be deleted from the account-wide library without restoring the workspace
  first. Other writes to an archived workspace remain blocked.
- Review closure: an independent correct review of an objective now closes every
  older active error record for that objective, so `recent failure` and its
  +20 risk contribution do not persist after a successful review. A later
  qualitative pass does the same.
- Installer and package metadata for the `r11.6.8` handoff, including the split
  release assets and checksums.

Verification performed for this source update: installer self-test passed with
184913 files, full payload CRC passed 184913/184913, the two changed runtime
files match the regenerated payload manifest, and the review-closure rule was
tested on an in-memory copy of a real mastery state (active errors 2 → 0; hinted
and non-review answers unchanged). This is not a claim of a new-PC cold install
or complete end-to-end acceptance. The dated record is in
[PROJECT-LOG.md](PROJECT-LOG.md).

The 4 GB installer is published as split release assets, not as a Git object.
The older r11.1 notes below retain their original scope.

---

# DeepSteam r11.1 source update

Source version: `2026.10.17-r11.1-review`.
Paired installed version: `2026.10.17-r11.1-review-local`.
Current paired OpenMAIC build: `RcB4EAVNrNtSnX1ppnha5`.

The review patch starts from public commit `ff0bb0eb181881c44b6bd1396179d171dae7b52c`.
It repairs admission/cancellation/rebinding, teacher inheritance, immutable file
delivery, source pagination and scoped identity, extension/repair transactions,
upgrade ownership and acceptance gates. Actual model tests also found and fixed
workspace-local archive access and Windows attachment staging length. Read the
[item-by-item review disposition](docs/review-remediation.md) before treating any
normal-path result as proof of unattended long-running reliability.

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

For independent review, use this commit's source, [review guide](docs/review-guide.md)
and [remediation record](docs/review-remediation.md). The supplied review was acted
on; its model/author identity and a fresh external approval of these fixes are not asserted.
