# Project status: October 18, 2026

The r11.5 competition candidate freezes the current features and dependency
versions. It includes the video revision and quiz-plan repairs in the common
regression suite, recoverable Windows reading-directory publication, a shared
feature profile, and expanded release evidence requirements. Both UIs are rebuilt
from the candidate source; the desktop ASAR and both Python source mirrors are
checked against it. This candidate has not passed complete live UI journeys,
two-hour mixed use, or second-PC installation lifecycle acceptance. Historical
results below are not results for this candidate. No live installation or user
records are replaced by the source preparation.

Candidate packaging also excludes the installation-specific storage selector and
previous uninstall inventory. Shipping either could point a different PC at the
builder's data location or preserve obsolete ownership records. Release identity
files are now included in the source/runtime binding checks.

Fresh-state background testing found a missing classroom dependency closure and
a startup result that reported success after its child exited. The stage now
includes the pinned dependency closure; the launcher returns failure on child
exit or startup timeout. Locale initialization now renders visible feedback,
offers retry on load failure and preserves an already mounted workspace while
changing language. The initial reproduction and post-fix tests are retained
separately. These fixes still require the final candidate's complete UI regression.

The subsequent r11.4 source update includes the accepted provider-ID, bounded
recovery and stable transcript-scroll repairs. The [release gate](release-gate.md)
now requires regression, real account inference, exact candidate installation
and native fullscreen acceptance. A background test cannot satisfy the native
gate. New source/test changes invalidate earlier receipts, and candidate builds
are not releases. Previously delivered r11.4 archives remain historical artifacts;
they are not retrospectively certified by this new gate.

The current source combines the r11 execution migration with subsequent experience fixes. This ledger retains known limits rather than treating a deployed patch as universal acceptance. Detailed private logs and screenshots are not published.

The r11.3 [second-review ledger](second-review-remediation.md) addresses ten
remaining boundary defects and a gateway mismatch found by actual model checks.
It supersedes broad cancellation/recovery/maintenance claims in the historical
[r11.1 ledger](review-remediation.md) with specific tested guarantees. The current
layout refinement is retained. Upgrades do not control or restart the native client.

The r11.2 [installer theme update](installer-theme.md) aligns native maintenance
windows with the existing dark application palette and is retained in r11.3.
The second architecture review examined commit `9a8dba5`; r11.3 is its subsequent
remediation, with the exact tested source fingerprints recorded separately.

| Issue group | Included change | Recorded status |
| --- | --- | --- |
| Startup and launcher (001-002) | Correct stale junction inventory and read the validated release identity | Startup passed; final launcher footer screenshot not obtained |
| Answer history and recovery (003-004, 024) | Keep Harness metadata, turn-scoped replay and canonical public RESULT persistence | Real Partner answer survived refresh; contract and stream regressions passed |
| Provider catalog (005) | Repair configured-service catalog loading | Loader checked; unconfigured providers have no live acceptance |
| Classroom layout (006, 016) | Preserve tables, formulas, labels, charts and readable pagination | Targeted regressions passed; sparse pages and some fragmented layouts remain |
| Reading/import (007-010) | Large PDF indexing, page persistence and current-page question scope | Real large import and navigation checked; indexing is not full OCR/understanding |
| Source tree (011) | Repair nested source-directory scrolling | Native check passed |
| Personalized learning (012-013, 019) | Visible teaching, blank-answer handling, text-source classification and collapsed internal mastery details | Focused native flows checked; mastery is not inferred from generated output |
| Classroom access/configuration (014-015) | Repair blank embedded view and video/model controls | Relevant native flow checked; auxiliary model services still require configuration |
| Navigation/export (017-018) | Return to workbench; video-export progress/cancel/recovery/download | Actual video rendered and opened; unified embedded/standalone export store remains pending |
| Notebook scope (020) | Preserve notebook workspace while navigating | Native flow checked |
| Source IDs and image references (021-022) | Resolve trusted persisted aliases and publish verified source previews | Actual source previews and cache reuse passed; old broken historical links not rewritten |
| Fullscreen (023) | Permit trusted user-initiated application fullscreen | Native classroom and actual exported-video checks passed |
| Sidebar continuity (025) | Retain account/workspace-scoped in-memory views; reject stale responses | Eight regressions and background route checks passed; final native retest deferred |
| Classroom prefetch (026) | Refill ready work before narration, bounded to two content calls | Eight scheduler checks and one real paired run passed; performance distribution unmeasured |

## Remaining validation and work

- Repeat classroom timing across more sources; reduce sparse pages and avoid unnecessary layout retries without dropping content.
- Complete subtitle auto-follow/highlight coverage and sustained playback checks. Keep account/session and subtitle-fetch status separate.
- Recheck task-board drag interactions; button-based changes passed but one drag attempt failed without a confirmed cause.
- Exercise a whole-book course workflow beyond indexing and selected-page reading.
- Test configured search, RAG, speech and image providers independently; model chat authorization does not configure them automatically.
- Expand extension/self-repair acceptance beyond the isolated sample and the exact version tested.
- Reconcile embedded and standalone export-store behavior and the remaining PPT formula horizontal-stretch case.
- Recover remaining compiled-only native frontend fixes into canonical source and demonstrate a full clean installer build.

The latest background phase did not control or restart the native client. Previous native observations and new background checks are labeled separately. The current repository publication updates code and records; it does not change installed user data or distribute a new binary.
