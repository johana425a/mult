# r11.1 architecture review remediation

Historical first-round evidence. The [r11.3 second-review ledger](second-review-remediation.md)
records remaining defects, subsequent fixes and narrower current guarantees.

This revision addresses the user-supplied review of the r11 Harness integration.
The review text is retained privately with SHA-256
`51653a0134224c9424ea08a9e98967f3b6f46e269729bf5694924f1c9ea7fa2b`.
Its author/model has not been independently authenticated. Findings were checked
against source and reproduced locally before changes. The existing five-entry
Harness architecture is retained.

## Finding disposition

| Review item | Change and evidence | Boundary |
| --- | --- | --- |
| 1. Teacher binding | Child admission inherits the parent's owner, workspace, model snapshot and source references; a stable parent ID exists before POST acknowledgement. Adapter regressions change the global selection during a parent run. | Inheritance is tested; this does not replace multi-user classroom authentication. |
| 2. Cancellation, timeout and transport budget | Teacher and native-child abort signals reach Harness; domain tools use the shared timeout wrapper; configured budgets count actual provider transports. | An absent configured budget is not represented as a finite one. |
| 3. Pre-followup failure | Attachment processing failures produce a durable failed turn before model invocation. | Old historical incomplete records are not fabricated as successes. |
| 4. Admission/cancel race | Serialized admission, durable cancellation tombstones and cancel-by-stable-request cover an accepted POST whose reply was lost. Cancellation is checked after asynchronous setup and cascades to children. | An already completed side effect cannot be undone by cancellation. |
| 5. Restart and operation recovery | Fresh teaching closures can rebind to the same original task with matching owner, workspace, conversation, tool schemas and source identity. Durable operation receipts distinguish completed and uncertain operations. | Completed calls with the same operation ID are reused. Arbitrary newly invented tool-call IDs do not establish semantic deduplication. Uncertain writes are not blindly replayed. Legacy tasks without compatible identity may require a new explicit turn. |
| 6. Event range | Each execution has a run ID and terminal sequence boundary. Later turns cannot leak events or live responses into an older completed task. | Historical events remain historical; they are not executed. |
| 7. External file delivery | Authorized outputs are validated from immutable snapshots and staged into the native workspace before attachment publication. | Native and Harness download paths are separately tested. |
| 8. Immutable downloads | Presentation and download use the same content-addressed bytes, SHA-256 and 64 MiB limit. JSON is parsed, not only decoded. | Pre-snapshot historical links cannot reconstruct already-overwritten original bytes. Present the surviving file again. |
| 9. Reading pagination | Requests beyond 24 units return the remaining range and a continuation cursor. A unit exceeding 60k characters can resume within that unit, bound to material revision. | This is source delivery, not proof of model comprehension. |
| 10. Source identity and archives | Trusted aliases are owner/workspace/source/version scoped; equal SHA alone cannot merge independent sources. Archives keep available original message objects in a hashed JSON file plus a readable text projection. | The snapshot is not a recording of every UI/runtime event. Mastery remains separate. |
| 11. MCP lifecycle | Repeated removal is idempotent; enabled state matches active configuration. Configuration and registry share a recoverable transaction. Reinstalls use distinct versioned directories. | Lifecycle regressions use deterministic decisions and real files, not a fresh cloud-model plugin search. |
| 12. Repair lifecycle | Live application descendants cannot bypass the stopped-service guard. Per-mutation durable intent permits reconciliation after real process death. Check output is redacted; a successful command cannot certify the behavior fix. | Arbitrary self-repair safety is not claimed. |
| 13. Upgrade transaction | Explicit file/tree plans record intent and prior/new hashes before replacement. Interrupted application and rollback reconcile the actual bytes. | A conflicting independent edit is rejected rather than overwritten. |
| 14. Uninstall ownership | The actual local deployment refreshes ownership, executables, installation metadata and registry through a durable updater transaction. | The user's real installation was not uninstalled. Real uninstall checks used disposable copies. |
| 15. Runtime ownership | Public PGlite program files enter the ownership inventory. User extension directories and data remain protected. | No broad recursive removal of extensions. |
| 16. Deployment evidence | Complete staged trees are compared file by file, and protected data is hashed before/after each stopped-service upgrade. | HTTP 200 and BUILD_ID alone are not the deployment proof. |
| 17. Acceptance gate | Required case IDs, formats, nonzero files, SHA/size, real download bytes and parsed source markers are mandatory. Empty or incomplete manifests fail. | Earlier successful downloads are retained as historical evidence, not retroactively dismissed. |
| 18. Provenance and reproducibility | The recovery checkout, r11 publication baseline, review patch and installed OpenMAIC output are identified separately. | Full clean-checkout reconstruction of the entire native installer remains **unverified**. Earlier compiled-only native frontend patches still require source recovery. |

## Additional defects caught by actual model tests

1. An internal learning-record call validated the owner/workspace but did not
   enter that workspace's storage context. A real conversation containing a user
   message therefore produced a zero-message archive. Notebook and history access
   now run inside the admitted workspace; empty original history produces an
   explicit error without saving a success-looking archive. Message `parts` are
   included in the readable projection when present.
2. A long Chinese workspace path, turn directory, snapshot hash and temporary
   suffix exceeded Windows' ordinary path limit during attachment staging.
   The authored files existed, but native attachment delivery failed. Snapshot
   staging is now compact and atomic file writes use Windows extended paths.
   A real filesystem regression crosses the temporary-name limit.

## Evidence categories

The focused suite has ten groups covering real process/file operations with
deterministic or mocked model decisions. It includes actual process termination
at repair, upgrade and installer ownership mutation points, plus disposable
uninstall checks. Native desktop control remains intentionally skipped.

Installed acceptance separately uses the configured real GPT-6.1-Sol model with
high reasoning through the native WebSocket and OpenMAIC HTTP/SSE routes. Initial
failed cases remain in the private record; they are not relabeled as passes after
repair. Download validation reopens the exact downloaded files and checks Chinese
PDF text plus Word headings, two-column tables, bullets and PAGE fields.

See the [review acceptance report](../reports/r11/review-acceptance.json) for the
final measured case outcomes. Timings are individual observations, with some
requests overlapping; they are not a performance guarantee. No foreground
window, mouse or keyboard was controlled, and the native desktop was not restarted.

The local installation was updated with rollback receipts. This source update
does not create or replace a desktop distribution archive or removable-drive copy.
