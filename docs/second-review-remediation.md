# r11.3 second architecture review remediation

The existing five-entry Harness execution architecture is retained. This revision
addresses the ten concrete remaining findings in the user-supplied second review
of commit `9a8dba5c9aadec0cfb02b7f9ab56c03da40d8862`. The review file SHA-256 is
`492fb780d73aabc1d20f228ce3218e0346c604335622e6083fc9488d6becc6a4`.
The report's accompanying independent evidence archive was not supplied locally;
the checks described here were run separately on Windows.

| Finding | Implemented behavior | Verified boundary |
| --- | --- | --- |
| T1: cancellation survives restart | Persist cancel intent and parent cancellation; reject rebind/resume of cancelled tasks; repeated cancellation of an older task does not cancel a newer turn sharing its session. | Queued, running, cancelling, failed and interrupted fixtures, legacy parents, restart and retry. Completed side effects are not undone. |
| O7: child questions reach the original interface | A child without native question tools can return `request_parent_input`; the parent publishes the envelope through `ask_user` or `cue_user`. Old generic questions are transferred and their hidden waiters cancelled without fabricated answers. | Adapter checks cover both surfaces, multiple questions, repeated HTTP callbacks and reconnect. Actual model checks separately exercise native question events. |
| N1: record operation identity | Record receipts include owner, workspace, task, agent and call, with argument fingerprints. Legacy identities are conversation scoped. | Same-call IDs across different tasks remain distinct; exact retries reuse records; conflicting arguments fail; archive/summary/mastery remain separate. |
| L1: cold ledger concurrency | Single-flight loading and serialized complete read/modify/write operations. | Concurrent 2, 10 and 100-source cold starts preserve all sources after reopening. |
| L2: extraction-version evidence | Source keys bind owner, scope, source ID, revision and SHA. Prior evidence remains archived and is excluded from current completeness. | Same bytes with a changed extraction revision cannot inherit completion or summaries. |
| T2: source binding on recovery | Freeze current material/source and workspace-grant identity, recheck native teaching calls, and reject changed snapshots on rebind. | Same-snapshot connection changes work; source revisions, changed source lists and changed/revoked grants fail. |
| U1: protected upgrade paths | Validate change/protection/journal overlap before staging and before target writes; validate results before success status. | Equal, ancestor, descendant and case/separator variants; changed protected bytes; real process-death recovery. |
| R1: credential log handling | Redact entire credential header values, structured nested fields and known command arguments. | Synthetic multi-cookie and authorization fields in successful/failed checks and command logs. Arbitrary unknown secrets in free text are not claimed detectable. |
| G1: artifact acceptance | Require nonblank, case-owned source markers and format parsers. HTTP acceptance requires independently received bytes and a corresponding HTTP receipt. | Empty/blank/wrong markers, wrong bytes, same source/download file and incomplete manifests are rejected. Local-only verification is labeled separately. |
| G2: complete-suite acceptance | Each run has one source fingerprint/toolchain/run ID and unique logs; selected checks never certify the full expected suite. Source changes during a run invalidate acceptance. | Missing, duplicate, unknown, mixed-run, mixed-source, skipped and failed cases cannot produce full acceptance. |

## Additional findings from actual model checks

The first real learning-record test caught an omitted gateway allowlist field:
the record tool supplied its new operation identity but the intermediate gateway
rejected it. The route now forwards that authenticated field, with a test of the
actual request parser and route function that also rejects unknown fields. The
failed real run is retained and is not relabeled successful because its chat
turn ended normally.

A transient preflight failure for `todo_write` was misleadingly described as a
protected-path denial. The original cause was discarded by the old catch and
cannot be reconstructed. Non-path preflight failures now retain their actual
sanitized code/message. A successful later call does not prove every possible
transient service error has been eliminated.

## Evidence and limits

The final fixed-source run `5f50e1f81e174c7ca3453d8281be8ede` passed all eleven
expected groups in 252.537 seconds (sum of group wall times), with source
fingerprint `1a906a6756d234b87fdfe6a68e28b7fb6cd9cb07635429d9e22f4317e757c88b`.
An earlier run rejected its total result when files changed during execution.
The production OpenMAIC build completed in 351.047 seconds, build ID
`dryxwUSkkn1IOtHk46iU8`.

Actual checks used the configured GPT-6.1-Sol model with high reasoning through
the installed entry adapters. They did not use a fixture model or operate the
desktop interface. Times below are single-run endpoint wall times, not latency
guarantees.

| Entry and action | Actual outcome | Seconds |
| --- | --- | ---: |
| Chat: MD, Word and PDF | All three files generated, parsed and independently downloaded | 178.612 |
| Chat: edit the same Word | New version delivered; old download still has its original bytes | 55.863 |
| Chat: task list | Two actual calls changed one item from in-progress to completed | 32.035 |
| Learning: first summary after gateway fix | Saved and read back | 33.372 |
| Learning: second distinct summary | Saved under a different record identity | 56.326 |
| Learning: after service restart | Read both, append once to the first, second unchanged | 47.632 |
| Reading: 30 Bilibili subtitle segments | Two source pages read; source-grounded MD delivered and downloaded | 288.348 |
| Workbench: ask and answer | Native question event; answer after service restart | 66.850 + 10.628 |
| Classroom: teacher question and answer | Child request transferred through native cue; answer after service restart | 107.088 + 44.241 |

Five actual HTTP file downloads passed independent byte/hash and format checks.
The original Word has a heading, two-column table, bullets and a PAGE footer.
The Chinese PDF text and rendered first page were checked. The reading document
uses the first and last returned segment start times; an unavailable last-segment
end time was not invented. Learning records retain `mastery_asserted: false`.
The initial learning run took 103.027 seconds and failed record acceptance before
the gateway patch; its normal conversational completion is not a success result.

The local r11.3 activation and subsequent three-file gateway/diagnostic update
passed byte checks, preserved eleven data roots, checked six HTTP services and
validated the installed uninstall entry. Native desktop process sets were
unchanged during each activation. Only managed backend services were restarted.

The Windows suite uses deterministic model decisions with actual filesystem,
subprocess and persistence operations. Its eleven groups are distinct from the
configured-model HTTP/WebSocket/SSE acceptance. Additional isolated checks use
a 420-character Chinese/space path, an exclusive Windows file lock and a real
junction escaping the target root. C# checks terminate the process at six
ownership-refresh points and exercise six disposable uninstall cases.

The production OpenMAIC build includes its real build TypeScript check. The
installer/uninstaller retains the current dark palette, Chinese labels and gold
particle icon. A rollback transaction verifies installed file/tree hashes and
eleven protected data roots; ownership refresh and the installed uninstall entry
are checked. The native client is not restarted or controlled.

Measured outcomes and their exact tested source fingerprint are in
`reports/r11/second-review-acceptance.json`. Private raw events, receipt files,
account material and downloads are retained locally, not published. The public
source snapshot may include subsequent documentation and manifest changes; its
production-source byte/canonical hashes are paired separately with installed
outputs. The complete native installer has not been rebuilt from a clean checkout.

This work does not certify unrestricted self-repair, arbitrary Skill directory
crash recovery, multi-account OS isolation, every model provider, full textbook
understanding, or long unattended operation. The real user installation was not
uninstalled. No desktop or removable-drive distribution archive was replaced.
