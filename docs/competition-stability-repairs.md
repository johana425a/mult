# Competition candidate repair record

Version: 2026.10.18-r11.5-contest-rc1. This is an unreleased candidate.
Dependencies remain pinned. Existing customer installations and data are not test fixtures.

## Shared failures addressed

* Preserve staged originals and rollback journals when Windows prevents reading-library directory publication. A later open can recover rather than discard the original.
* Bind all shipped application copies, the desktop archive and compiled UIs to their source inventory. Stale secondary Python copies and changed builds invalidate prior acceptance.
* Exclude machine-specific storage selectors and old uninstall inventories from payloads.
* Retain a complete internal pinned classroom dependency graph; report startup failure if the child dies or readiness times out.
* Show initial locale-loading feedback and a retry action without remounting an existing draft after language-loading failure.
* Use indexed on-demand import for small scanned PDFs as well as large PDFs. Index completion is not a claim that a model has read all pages.
* Read generated Chinese and space-containing Windows paths beyond MAX_PATH while retaining containment, reparse-point, opened-handle and source-hash checks.
* Compile document tool definitions using the actual pinned Harness schema DSL before starting the host.
* Block submission until the URL session is restored, including starter actions. Preserve typed drafts after failed or delayed restore. This prevents a new session from receiving a message intended for an old one.
* Apply the same restoration guard to reading and personalized-learning composers. A bounded reading-history load shows a retry action without discarding the draft.
* Keep local Windows HTTP listeners alive when a peer disconnects during accept (WinError 64). The application-owned Proactor loop closes abandoned sockets, yields between retries, retains async subprocess support, and still propagates cancellation and unrelated errors. No dependency upgrade or standard-library overwrite is used.
* Apply the requested 512 MiB shared-reader default to the ingestion queue and child processes too. Respect smaller explicit limits. The on-demand reading library has its separate large-book import path.
* Stream reading uploads through the existing backend forwarder, preserving authentication, workspace scope, cancellation and backend limits. Next Proxy's 210 MiB body clone previously truncated a 540 MiB textbook upload and left the UI waiting for the missing body.
* Connect PDF viewing to the already implemented browser-ready container route. Using the raw route bypassed that repair; the 4,381-page book failed with `Invalid string length` despite a complete import. Original bytes remain the reading source and download; page streams, geometry and native outline are checked before a display copy is published.
* Use 1 MiB PDF range chunks: the default 64 KiB size caused thousands of simultaneous requests for a large flat page tree, exhausting Chromium request resources. A stalled open has a deadline and retry, and cancelled workers cannot leave unhandled destroy errors.
* Honor an explicitly requested quiz language through exploration, planning, individual questions, repairs and follow-up. The interface language remains the default; source-language text alone does not change it.
* Persist submitted quiz answers in an account/workspace/session/turn-scoped pending draft before sending. A failed save keeps the answer across reload, exposes a retry, and cannot report a completed learning record. Successful writes clear only their own draft revision. Duplicate submissions and redo during a write are blocked, and requests have a bounded timeout. Local storage failure is reported without promising persistence. Aggregate learning-record failures have a separate retry.

## Added release regressions

* Reconcile a first-send draft that was accepted before the browser received its session binding, using the persisted submission ID when history is reopened. Equal-text drafts from other submissions remain recoverable.
* Resume visible execution state after the server consumes a restored clarification answer. Retain the same turn, replay cursor and assistant message; a queued ACK or historical event does not start another turn.
* Queue video controls until the official Bilibili player is ready, and prevent late saved-position loads from overriding explicit seeks. Transcript hydration cannot remount the native player or reapply an old position.
* Move verified internal TLS initialization, model SDK initialization and reading-extension discovery off the service event loop. Keep certificate verification, workspace context, model identity and cancellation cleanup.

The unified runner includes video revision, five noncoding quiz types, interrupted directory publication, scan indexing, deep Windows output paths, complete shared-reader contracts, tool DSL compilation, child size limits, locale failures and session readiness. Synthetic fixtures, real-model checks and background-browser journeys are reported separately.

Some older reader tests expected the retired `needs_ocr`/`none` state. They now assert the current `partial`/`visual_only` contract and pending original images. The OCR budget test sets the actual page counter and cap. Windows reparse-point coverage uses a real directory junction without skipping for unavailable file-symlink privileges.

## Acceptance boundary

Preliminary testing includes a new-scope 7.4 MB, 62-page scan import in about 4.6 seconds, a real GPT answer from its original last-page image, and real generated MD, DOCX, PDF, XLSX and PPTX readback/downloads. These are diagnostic results on an evolving candidate, not final-package approval. Only actual final-package evidence may satisfy the release gate. Native fullscreen, second-PC lifecycle and two-hour mixed use must still be independently completed. No time deadline overrides a failed gate.
