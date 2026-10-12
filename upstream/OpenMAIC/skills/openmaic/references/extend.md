# Extend Or Build On OpenMAIC (extension development)

## Charter

Secondary development is a confirmation-heavy, **read-before-modify** guidance flow — not a generation flow. Help the user understand the existing code first, then make targeted changes. Default to **not** editing source under `packages/@openmaic/*`; consume those packages as-is. (Modifying the SDK itself is a different, heavier path — see the last section of [extend-sdk.md](extend-sdk.md).)

This reference takes priority over the `accessCode` auto-shortcut in Phase 0: if the user's intent is to extend / build on / customize OpenMAIC or consume the `@openmaic/*` SDK, enter this flow **even when a stored `accessCode` exists**. A returning Live Demo user who now wants to do extension development should be routed here, not silently sent back to Live Demo.

## Secondary-Development Rules

1. **Read before edit.** Before changing any file, read it (and the symbols it imports) so the edit matches surrounding conventions. Do not paste large code blocks into chat — point the user at `file:line` entry points and let them read.
2. **Toolchain is hard-required.** `pnpm@10.28.0` (root `packageManager`), Node `>=22.19.0` (`.nvmrc` pins `22`). Mismatched pnpm will fail install.
3. **Forking and disabling CI are conditional, not defaults.** Decide per the user's intent — see Development Environment below — instead of reflexively forking every user.

## Development Environment (Same As Local Deployment)

The extension-development environment is the OpenMAIC **local deployment environment**: the same toolchain, repository, `pnpm install`, provider keys, and startup modes. **Do not create a separate setup procedure here.** Follow standard local deployment to obtain a working instance, then add the extension-specific changes.

**Where to get the code (choose as needed; a fork is optional):**

- **Personal use / no remote needed:** clone upstream `THU-MAIC/OpenMAIC`, then modify and run locally. No fork or CI setup is needed. Without upstream write permission, accidental upstream pushes are unavailable. Use local commits on a branch for version rollback.
- **Remote needed** for backup, multi-machine synchronization, collaboration, GitHub deployment, or upstream contributions: fork, clone your fork, then push to it. The fork provides a remote that you can write to.

**Installation and startup:** reuse the existing local-deployment references rather than rewriting the process: [clone.md](clone.md) covers cloning and `pnpm install`, whose postinstall builds all `@openmaic/*` packages and synchronizes vendor packages; [startup-modes.md](startup-modes.md) covers startup; [provider-keys.md](provider-keys.md) covers provider keys.

**Disabling publication CI: triggering a workflow is different from running a publish job.** A fork includes `.github/workflows/publish-packages.yml` and `publish-openmaic-skill.yml`. Check two layers:

- **Trigger layer:** `publish-packages.yml` triggers only for a **push to main that changes `packages/@openmaic/*/package.json`**, not a pull request. `publish-openmaic-skill.yml` triggers for a **pull request or push to main changing `skills/openmaic/**`**.
- **Job layer:** on **pull requests**, `publish-openmaic-skill.yml` runs only Bash 3 compatibility and dry-run preview jobs, neither of which needs a token. The **publish job using `CLAWHUB_TOKEN` runs only on a push or a manual non-dry-run dispatch on main**. The `publish-packages.yml` publish job using `NPM_TOKEN` also runs only on pushes.

Token failures in a fork therefore arise **only from pushes matching the triggers**, not pull requests. Feature-branch pushes outside the trigger conditions do not run the workflow. Disable publication workflows or remove triggers if your fork pushes matching changes to main; otherwise no change is needed. Local-only use without pushes also needs no change. Environment and token gates prevent accidental publication.

**Run and verify after changes:** follow [startup-modes.md](startup-modes.md) and [provider-keys.md](provider-keys.md). Check `GET {url}/api/health` and verify UI or route changes in the browser. When changing **source** under `packages/@openmaic/*`, rebuild the corresponding `dist/` first: consumers resolve `dist/`, not `src/`. Dependency order is `dsl -> generation -> storage -> importer -> renderer -> editor`; `pnpm install` postinstall follows it. Use each package's `pnpm run build` for an individual rebuild.

## Route To The Right Sub-Reference

Ask the user which of these they want. When unsure, offer 2–3 examples (below) and let them self-identify before loading anything.

- **Customize the OpenMAIC product itself** (change a feature / UI / swap in your own provider, storage, or theme / add a page or API route / embed the renderer or editor inside the product) → Load [extend-cookbook.md](extend-cookbook.md).
- **Use the `@openmaic/*` SDK to build a new, standalone app** (outside this repo — `npm install @openmaic/renderer` into your own project, not a monorepo workspace) → Load [extend-sdk.md](extend-sdk.md).

Typical examples to help the user pick:

- "I want OpenMAIC to call my company's LLM / write to my S3 bucket / show my branding" → **cookbook** (you are modifying the product).
- "I want to render OpenMAIC slides, or embed the slide editor, inside my own separate app" → **SDK** (you are consuming packages, not editing the product).
- "I want to add a feature to OpenMAIC and ship it in the product" → **cookbook** (modifying the product).

## General Gotchas

Each is tagged with where it bites: **[product/fork]** (working inside the OpenMAIC repo), **[SDK]** (consuming packages in a separate app), or **[both]**.

- **[product/fork] `dist/` is gitignored in a source checkout.** In a fork/monorepo, each `@openmaic/*` package ships source only; its `dist/` is produced by `postinstall` (builds `dsl → generation → storage → importer → renderer → editor` in dependency order). If you `git clean -fdx` or nuke `node_modules`, re-run `pnpm install` or the packages won't resolve. (Published npm packages — the [SDK] path — ship built `dist/`, so this does not apply there.)
- **[product/fork] The vendor bundle is asserted before build.** `pnpm build` runs `node scripts/assert-vendor-maic-importer.mjs && next build`. That guard `stat()`s `public/vendor/maic-importer/index.js`; if missing/empty it exits 1 with an actionable message. `postinstall`'s `sync-maic-importer.mjs` step populates it — re-run `pnpm run sync:maic-importer` if you cleared it.
- **[product/fork] `workspace:*` are symlinks.** Inside the monorepo, `@openmaic/*` resolve to live `packages/@openmaic/*` source via pnpm workspace links. Editing a package's `src/` is picked up on its next build — but consumers see the built `dist/`, not `src/`, so rebuild the package after source changes.
- **[both] The renderer hard-depends on Tailwind v4.** `@openmaic/renderer` has `tailwindcss: ">=4"` as a peer. Tailwind v4 uses `@theme`/`@source` CSS directives, not a JS config — see [extend-cookbook.md](extend-cookbook.md) (branding) before touching styles.
- **[product/fork] `@/*` path alias** is anchored at the repo root (`tsconfig.json` → `"@/*": ["./*"]`), not inside `packages/`.
