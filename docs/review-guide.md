# Independent architecture review

Review the code at one fixed commit, not only the README or acceptance claims. The intended design is one Harness loop for chat, personalized learning, immersive reading, OpenMAIC workbench and classroom dialogue, with each surface retaining its domain services.

Start with [architecture and entry points](architecture.md), [real and deterministic validation](validation.md), [known open work](project-status.md), and [build coverage](source-provenance.md). The sanitized machine-readable record is [acceptance-summary.json](../reports/r11/acceptance-summary.json).

Prioritize these questions:

1. Does any interactive route still enter a second general agent loop, silently change model, or lose configured tools?
2. Are model/reasoning/configuration snapshots stable for a turn? Do adapter errors preserve actionable details?
3. Can session, workspace, owner or source identities be confused across entry points, reconnects or concurrent requests?
4. Do cancellation, model failure, disconnect and restart avoid false success, duplicate tool execution and duplicate file writes?
5. Can transcript paging or source adaptation truncate content while claiming whole-source completion?
6. Do attachment checks and file-scoped links preserve source identity and prevent access outside the admitted owner/workspace?
7. Does Partner persistence receive one authoritative result while streaming, failures and cancellation preserve their original meaning?
8. Do extension installation and repair retain version/ownership records, verify staged changes, and permit actual rollback without overwriting a live core?
9. Does bounded prefetch preserve ordering, failure and cancellation without exceeding the intended concurrency? Do sidebar snapshots clear across auth/workspace changes?
10. Are distribution and source-rebuild claims supported by the available source, manifests and actual tests?

For each finding give the file and line, concrete trigger, observed or inferred impact, and a minimal verification/fix proposal. Separate confirmed defects, already-fixed observations, untested risks and optional improvements. Tool registration, fixture success and source indexing are not end-to-end acceptance or proof of learning completeness.

The repository contains no model credentials, private user records or full retained textbook fixtures. Optional retained-draft tests require the reviewer's own consented fixtures. Do not request private account data to substitute for a reproducible synthetic case.
