# DeepSteam modification notice — 2026-10-10

This is a modified integration/distribution of the pinned projects described in
`NOTICE.md`. Upstream LICENSE files and source copyright notices are retained.
The distribution also includes licenses for bundled dependencies and runtimes.

This revision changes these user-facing integration files:

- `portal/static/index.html`: uses the DeepSteam name, functional settings and
  service labels, concise competition AI attribution, and a local/API selector.
- `portal/static/app.js`: preserves custom API form values, submits
  `model_mode`, and explains the selected model using functional names.
- `upstream/DeepTutor/web/components/education/EducationStudio.tsx`: original
  DeepSteam classroom add-on; replaces architecture-oriented descriptions and
  links with model/classroom settings, preserves the settings functions, adds
  the local/API selector, and retains concise AI attribution.
- `README.md`, `HANDOFF-搭档先读.md`: update portable installer verification
  status and separate the previous installer acceptance from the pending local
  model acceptance.
- `upstream/OpenMAIC/app/page.tsx`, `app/layout.tsx`,
  `components/stage/scene-sidebar.tsx`, `components/access-code-modal.tsx`,
  `components/scene-renderers/pbl/v2/workspace.tsx`,
  `lib/brand/brand-config.ts`: visible application name/logo and functional
  metadata use DeepSteam. The layout and brand configuration include explicit
  modification comments; this notice records all the changes together.
- `upstream/OpenMAIC/public/deepsteam-wordmark.svg` and `deepsteam-mark.svg`:
  copy the existing original integration artwork used in the DeepSteam shell;
  original upstream assets remain in the source distribution.

No personal DeepTutor installation or Obsidian Vault data is included by these
changes. API settings and upstream functionality are retained. Other revision
files (runtime, local model routing, installer) are recorded by their respective
release reports; this list specifically records the UI/notice portion.

Related local classroom-provider refinement (completed by the integration task
and included in the subsequent 20261010-211410 production build):
`upstream/OpenMAIC/lib/ai/providers.ts`, `lib/store/settings.ts`, and
`lib/server/provider-config.ts` register an independent keyless local provider,
provide fresh-browser defaults, and support its server configuration mapping.
Existing valid custom API choices remain available. The integration task's
focused contracts and the later real model tests are separate from frontend
production compilation.

Apache-2.0 file-level modification notices were added on 2026-10-10 to every
tracked modified DeepTutor frontend file listed below. The notices are one
source comment per TS/TSX/CSS file, or one legitimate metadata string in each
locale JSON dictionary. They do not replace the original license or expose
architecture descriptions in normal teaching UI:

- `web/app/(auth)/login/page.tsx`
- `web/app/(auth)/register/page.tsx`
- `web/app/globals.css`
- `web/app/layout.tsx`
- `web/components/chat/home/SessionLoadingView.tsx`
- `web/components/layout/AppShell.tsx`
- `web/components/settings/ThemePreviewCard.tsx`
- `web/components/sidebar/SidebarShell.tsx`
- `web/components/sidebar/nav-entries.ts`
- `web/features/chat/components/ChatWorkspace.tsx`
- `web/features/chat/trace/TracePresentation.tsx`
- `web/locales/de/app.json`
- `web/locales/en/app.json`
- `web/locales/fr/app.json`
- `web/locales/pl/app.json`
- `web/locales/uk/app.json`
- `web/locales/zh/app.json`

Subsequent OpenMAIC source-grounding refinement (integration task): the
uploaded document's original extracted text is retained as `Stage.sourceMaterial`
separately from the bounded generation prompt. Native generation retains the
full parsed text in browser IndexedDB, and completed classroom storage/export
includes the source field. Legacy excerpt-only sessions are explicitly marked
incomplete rather than described as full originals.

Native teacher context now includes exact source excerpts selected with a
2400-character prompt budget and question-aware lexical retrieval, plus a
1200-character budget for relevant other slide context. These are prompt
budgets, not destructive source-storage truncation. Source data is evidence,
not executable instructions; the prompt asks the teacher to preserve stated
quantities and conditions, check calculations, and state insufficient evidence
instead of inventing missing assumptions. Generation and feedback prompts
likewise retain the source boundary. This source-flow repair does not assert
that a 4B model will never make a factual or arithmetic error.

The original failed live native-teacher result is retained in
`reports/local-qwen-acceptance-first-native-failure.json`. It included the
incorrect statement that 20 / (20 + 80) was 0.1. Subsequent build results and
real model acceptance reports are recorded separately; earlier failed evidence
is not relabeled as a success.

Storage separation revision — 2026-10-11:

- `scripts/storage_paths.py` adds an explicit, installation-local storage
  selector. Factory installs keep their own state; only a user-selected
  `deepsteam-storage.json` selects a separate local writable directory. The
  selector is private machine configuration and excluded from share packages.
- `scripts/deeptutor_runtime.py`, `portal_runtime.py`, `openmaic_runtime.py`,
  `render_runtime.py`, `qwen_runtime.py`, and `initialize_deepsteam.py` direct
  owned databases, logs, process records, temporary files, and runtime caches
  to that selected directory. Program/model assets remain installation-relative.
  Initialization rebinds only owned catalog/material paths while preserving
  content, record identities and first answers.
- `upstream/OpenMAIC/lib/server/data-directory.ts`,
  `lib/server/classroom-storage.ts`, `lib/materials/bytes.ts`, and
  `lib/server/usage-storage.ts` retain native storage behavior by default and
  support an explicitly selected local data directory for classroom, materials,
  jobs and usage records.
- The staged Next.js generated server entries contain a documented narrow
  configuration change: when `DEEPSTEAM_SEPARATE_STORAGE=1`, the official
  `images.maximumDiskCacheSize` option is zero. Image optimization URLs,
  resizing and format handling remain enabled; disk image-cache writes are
  disabled. The factory configuration remains unchanged. The installer helper
  `stage_frontend_payload.py` records this generated-entry transformation;
  `test_next_image_cache.js` checks both modes against the bundled Next versions.

These storage changes do not alter teaching, grading, provider selection,
upstream API settings, or the factual quality limits of the local model.
