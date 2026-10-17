# Validation record

This record combines the October 17 Harness migration acceptance and the later standalone experience checks. It describes completed observations on one Windows machine. This source-publication task did not rerun every cloud-model scenario or produce a new installer.

## Real-model execution acceptance

The selected model was `gpt-6.1-sol`, reasoning `high`, frozen per turn. Requests used the actual native WebSocket or OpenMAIC HTTP/SSE entry points; these are real model calls, not fixture responses. Native attachment cards and playback received separate interface checks.

| Operation | Total seconds | Observed tool seconds |
| --- | ---: | ---: |
| Chat: MD, Word, PDF | 159.555 | 24.234 |
| Modify the existing Word document | 86.729 | 15.872 |
| Personalized learning and notes | 179.657 | 23.343 |
| Resume and extend learning records after restart | 171.181 | 16.565 |
| Complete Bilibili transcript to documents | 236.751 | 16.503 |
| OpenMAIC workbench | 185.831 | 29.984 |
| OpenMAIC classroom dialogue | 163.758 | Not exposed |
| Course editing and export | 110.557 | 0.167 |
| Classroom chat archive | 64.166 | Not exposed |
| Disconnect and resume the same task | 43.505 | 14.694 |
| Wait for a question reply and resume | 100.489 | 64.457 |
| MD, DOCX, PDF, XLSX and PPTX | 343.541 | 49.883 |
| Installed runtime: MD, Word, PDF | 186.095 | 30.009 |
| Installed runtime: direct execution | 26.728 | 5.699 |
| Installed runtime: workbench edit/export | 75.707 | 15.507 |

Tool intervals are merged when overlapping. The remaining time includes model service, network, event transport and polling; it is not isolated inference time. Missing tool intervals are not zero. The question test includes approximately 53 seconds of intentional test-response waiting.

Independent readback parsed **31/31 files**; authenticated download checks passed **22/22**. Word checks covered heading styles, two-column tables, bullets and page-number fields. PDF checks covered Chinese text and pagination. Learning records appended after restart; raw chat archives were preserved. A disconnect test retained a counter value of one, rather than writing twice.

The Bilibili check used a copy of the application's authorized session. Login/avatar status, 189 subtitle cues across two language tracks, playback/pause, seeking and 2x speed passed. Installed subtitle retrieval took 3.715 seconds. The model paged through the transcript before producing documents. This does not establish support for every video or platform.

The uninstall form opened in an isolated test desktop in 4.367 seconds, with default data retention. Actual removal of the production installation was not performed.

## Deterministic decisions with real tools

The following lifecycle checks used controlled model decisions but actual execution, files, persistence and extension operations: incompatible model parameters; failure details; cancel/restart; idempotent recovery; Chinese/long paths; missing dependencies; official MCP Memory `@modelcontextprotocol/server-memory@1.0.0` install/call/restart/read/remove/rollback; and isolated fault repair/validation/apply/rollback.

The runtime exposed 33 direct tools and 68 after loading extension groups. Four document skills loaded and their formats were exercised. These counts are **not** a claim that all 68 tool actions, providers or account combinations were tested. Desktop control was not operated during background-only architecture acceptance.

## Later experience observations

- Actual five-format generation: 225.884 seconds; follow-up modification: 203.474 seconds, with attachment/readback checks.
- Partner answer persistence: a roughly 9-second answer remained after refresh, with the canonical RESULT contract restored. Five focused contract tests and four stream regressions passed in that repair run.
- Original source-image previews and stable source aliases worked after refresh. Reused original-page checks took 0.002 and 0.001 seconds without new OCR/VLM calls.
- Two formula pages took 37.210 and 28.765 seconds for the observed learning flow. This is not a whole-book throughput result.
- A 540 MiB, 4,381-page PDF imported/indexed in approximately 9.2 seconds. Indexing is distinct from OCR, page interpretation or exhaustive teaching.
- A 51.625-second 720p video rendered in 72.385 seconds; fullscreen, pause, preview/download and return navigation were checked in the relevant native test phase.
- Eight sidebar regressions and subsequent background navigation samples passed; a native-client retest of the final sidebar patch was deferred because desktop control was paused.
- A real same-source classroom pair measured 659.803 seconds / nine slide pages before and 593.053 seconds / six slide pages after. Generated outlines differed (five versus four). Eight scheduler checks passed. This is one pair, not a statistically stable benchmark; one diagram draft still needed a bounded retry and one page remained sparse.

## Public source checks and limits

Focused regression entry points are in [tests/r11](../tests/r11/README.md). The publication checks source integrity, private-data exclusions, English defaults and syntax, and reruns the focused contract/scheduler/sidebar/layout cases. [Publication checks](../reports/r11/publication-checks.json) record their actual results and dependency reuse. [Sanitized acceptance data](../reports/r11/acceptance-summary.json) retains aggregate model timings without private sessions, file paths, accounts or chat content.

Still unproven: a complete clean-checkout installer build; a second physical computer with fresh model credentials; every registered tool/provider; long-running autonomous reliability; complete scanned-book understanding; exhaustive subtitle follow/highlight behavior; and all cross-format layout details. Task-board dragging and some classroom/PPT layout cases remain open. Tests and audits do not measure a student's mastery or guarantee teaching completeness.
