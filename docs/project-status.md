# Project status: October 17, 2026

The current source combines the r11 execution migration with subsequent experience fixes. This ledger retains known limits rather than treating a deployed patch as universal acceptance. Detailed private logs and screenshots are not published.

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
