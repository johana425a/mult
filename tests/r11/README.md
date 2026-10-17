# r11 focused regressions

Run from the repository root. These tests make no paid model calls. Node.js must support TypeScript type stripping for `test_prefetch_refill.mjs`; the paired runtime used Node 24. Use the Python version/dependencies required by DeepTutor for the pipeline contract test.

```powershell
node tests/r11/test_prefetch_refill.mjs
node tests/r11/test_sidebar_view_state.cjs
python tests/r11/test_harness_result_contract.py
node tests/r11/test_compact_flow.mjs
node tests/r11/test_semantic_slide_layout.mjs
node tests/r11/test_table_layout.mjs
```

- Prefetch: pure source scheduler, bounded concurrency, order, ready-buffer refill, failure and cancellation.
- Sidebar: React/JSDOM exercise against the published retained-state source. Install the DeepTutor web dependencies first. `DEEPSTEAM_WEB_TEST_DEPENDENCIES` can explicitly name an existing web `package.json` for dependency reuse; it does not replace the tested sidebar implementation.
- Result contract: imports this checkout's DeepTutor pipeline and mocks only the Harness outcome. Checks authoritative result, suppression, failure, surface identity and cancellation.
- Layout: build `@openmaic/generation` and its workspace dependencies first. Tests default to this checkout's `dist/index.js`. `DEEPSTEAM_GENERATION_DIST` can select a separately built source-matched generation package; disclose that reuse and verify source parity when reporting results.

`test_native_compact_draft.mjs <file>` and `test_chart_label_layout.mjs <directory>` are optional replays of consented retained drafts. Their private input data is intentionally excluded. The directory variant expects the three draft filenames listed in the test. They are not required clean-checkout synthetic tests and should not be reported as run without those fixtures.

Use `python scripts/verify_public_source.py` for publication-integrity checks. It verifies the manifest and public defaults without reading private configuration. Generated `dist`, dependencies and local results must remain outside the public source manifest.
