# Regression and release acceptance

The supported release flow now fails closed. An installer build is an
**unreleased candidate**, even when Windows self-test succeeds. Only
`installer/release_gate.py promote` creates a reviewed delivery directory.
There is no skip, force, or reuse-old-success switch.

The gate binds one run to the exact installer/payload SHA-256, source and test
tree, version, and run identity. Evidence expires after 24 hours. Editing source,
tests, artifacts or evidence invalidates acceptance. Existing release folders
are never overwritten. This is protection against accidental unverified release;
it is not a signature or security boundary against someone editing the gate.

## Required coverage

| Group | Automatic checks | Evidence boundary |
| --- | --- | --- |
| Model adapters | Provider-specific tool IDs, original stream/nonstream IDs, bounded transient recovery, no retry after output, auth/error/cancel handling | Synthetic transport cases |
| Real accounts | gpt-6.1-sol, DeepSeek Flash and DeepSeek Pro; plain answer plus read-tool-result-answer, fixed high effort | Actual configured providers; unavailable accounts fail |
| Answers | Streaming deduplication, authoritative result, persistence filter, failures cannot become successful answers | Real application boundary, synthetic Harness responses |
| Personalized learning | Lesson before quiz, terminal card, unsuccessful card, SQLite wrong/correct attempts and reopen, stale writers, rollback, original source images and source identity | Temporary records; never user mastery |
| Reading and quizzes | Caption revision identity, five noncoding question types, malformed-plan repair, bounded Windows rename retry and recovery after failed rollback | Real file operations with injected faults; synthetic plans are labeled |
| Classroom | Fresh generation-package compilation, bounded prefetch/cancel, compact pages preserving exact text/formulas/images/tables, quiz normalization/rejection, runnable interaction and stable scene identity | Actual generation code with synthetic model output; not a new full cloud classroom |
| Workspace | Retained first paint, scope/account isolation, late response rejection | React/JSDOM |
| Fullscreen scroll | Stable scrollport across three sizes and 21 offsets, final cue, observer cleanup, native fullscreen permission policy | Deterministic geometry, not native visual acceptance |
| Installed candidate | Windows self-test, cold install without launch, every payload file hash, junctions, source binding | New isolated installation only |
| Native fullscreen | Enter, scroll down/up, last cue, resize, exit, reopen, no oscillation; recording and reviewer required | Required separate native-client acceptance |
| Gate itself | Failures, skips, no assertions, timeout, missing cases, wrong model, stale source/evidence/artifact, output collision, positive synthetic promotion | No real installer distributed by these tests |
| Core journeys | Full reading, video, learning, classroom and file delivery UI flows; three configured models; three consecutive primary rounds including cold start and reopen | Actual product and real model calls; backend-only output is insufficient |
| Recovery and continuous use | Eleven fault cases and at least two hours of mixed use with resource samples, artifact binding and actual actions | A sleep loop or synthetic responses cannot pass |
| Installation lifecycle | First use, r11.4 upgrade, continued use, uninstall, reinstall and retained data on a different Windows x64 PC | Local empty-directory installation is insufficient |
| Visible features | One shared profile for navigation and direct routes; core features cannot be disabled; retained features and manuals match tested scope | Untested peripheral features are not automatically marked usable |

No checks impose a textbook page cap or remove content to improve speed.
Other providers receive the common adapter contract checks, but these must not
be described as successful real calls to unconfigured accounts.

## Background regression command

Use a source checkout and a fresh output directory outside it. Python needs the
DeepTutor dependency versions; Node must support TypeScript stripping. Explicit
dependency reuse selects libraries, not an older application implementation.

```powershell
$env:DEEPSTEAM_PYTHON_DEPENDENCIES = 'D:\staged-app\runtime\deeptutor-packages'
$env:DEEPSTEAM_WEB_TEST_DEPENDENCIES = 'D:\web-dependencies\package.json'
$env:DEEPSTEAM_GENERATION_DEPENDENCIES = 'D:\classroom-dependencies\packages\@openmaic\generation'
& 'D:\staged-app\runtime\python\python.exe' -B installer\run_release_regressions.py --out 'D:\acceptance\source-check-001' --node 'D:\staged-app\runtime\node\node.exe'
```

The runner always recompiles the current generation sources in its fresh output
directory. A supplied old `DEEPSTEAM_GENERATION_DIST` cannot bypass compilation.
Every group must execute assertions and exit successfully. Logs and timings are
retained. Selected historical review scripts alone cannot certify a release.

## Candidate and delivery commands

1. Synchronize program changes into a complete staged runtime. The builder checks
   every application source family, both Python copies, the actual desktop ASAR,
   and complete fresh frontend/classroom build inventories. Each build receipt
   must match source before and after compilation. Dependencies remain pinned,
   reused dependencies; this is not a dependency-free rebuild claim.
2. Build with `build_standalone_release.py --runtime-root <staged-app>
   --candidate-only --source-root <checkout> --out <new-folder.candidate>`.
   Installer self-test creates `acceptance/context.json` only on success.
3. Run `run_release_regressions.py --run <acceptance> --out <acceptance>` with
   the same source and dependencies. It runs all required groups.
4. Run `accept_installed_candidate.py --run <acceptance>`. The new install is
   retained at `<acceptance>/isolated-install`; it is not launched. Use a short
   candidate path because the Windows installer limits target path length.
5. Run the installed Python with `tests/release/live_models.py --source-root
   <checkout> --runtime-root <isolated-install> --account-root <authorized-local-app>
   --out <acceptance> --run <acceptance>`. Account grants are used locally; they
   are not copied into the install, test profile, receipts or release.
6. Perform native fullscreen acceptance on this candidate when desktop operation
   is allowed. `record_native_acceptance.py` requires a recording and a completed
   observation JSON containing the candidate `binding`, `reviewer`, `product:
   DeepSteam`, `evidence_class: native-ui`, every step from `NATIVE_STEPS`, at
   least 30 `samples`, and `max_scroll_drift_px` between zero and one. Do not
   create a passing observation from browser or geometry tests.
7. Record actual competition journeys, recovery, mixed use, feature coverage,
   and second-PC lifecycle evidence using the cases in `competition_acceptance.py`.
   Synthetic policy fixtures are tests of rejection rules, not product receipts.
8. `release_gate.py check --run <acceptance>` lists every missing or failed gate.
   `release_gate.py promote --run <acceptance> --out <new-delivery-directory>`
   rechecks, copies and rehashes every artifact, checks again, then renames the
   temporary output. A failed copy remains under `.unreleased-*` for diagnosis.

If a group fails, fix it and create a fresh run. A code change also requires a
new synchronized candidate. Source-only review ZIPs are not binary releases and
continue to use the existing source handoff tools.

The legacy document binary build/share commands are retired. The installed
`release-build.cmd` requires an explicit source checkout and only builds a
candidate. Historical one-off scripts and already delivered archives are not
retroactively certified by this gate.

Current desktop restrictions do not waive native acceptance. Background work
can pass its own groups while the final release remains blocked. No software
gate can guarantee that a remote model provider will never later return 502;
the gate catches reproducible integration failures and verifies recovery bounds.
