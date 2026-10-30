# DeepSteam project log

This is the dated record of program, packaging and publication changes. Every
program change or package rebuild must append a section here before it is
published. Times are local (Asia/Shanghai). Keep user data, credentials and
machine-specific paths out of this file.

## 2026-10-28 — Reading materials and collections can be deleted in archived workspaces

- Symptom: the account-wide reading library still listed materials and
  collections from archived workspaces, but deleting them returned HTTP 404
  `Restore this workspace before changing its data.`
- Cause: `_install_request_workspace` rejected every non-GET request against an
  archived workspace, including explicit library cleanup deletes.
- Change: allow `DELETE /api/reading/...` against an archived workspace. Other
  writes (create, upload, activate, position) remain blocked.
- Files: `upstream/DeepTutor/deeptutor/api/routers/auth.py`.
- Verification: a disposable archived workspace deleted a material (HTTP 200,
  `removed_from` returned) and a collection (HTTP 200); the real `111`/`222`
  data was unchanged. Installer self-test and full payload CRC passed.
- Package: installer payload and manifest synced; see the package sections
  below.

## 2026-10-28 — Books can be deleted in archived workspaces

- Symptom: a book in an archived workspace could not be deleted from the
  account-wide book library.
- Cause: the same archived-workspace request guard; book deletion uses
  `DELETE /api/books/{book_id}`.
- Change: extend the cleanup exception to `/api/books/`.
- Files: `upstream/DeepTutor/deeptutor/api/routers/auth.py`.
- Verification: a disposable archived workspace deleted
  `bk_f0896f1b74` (HTTP 200, `deleted=true`); the real `111` book remained.
- Package: installer payload and manifest synced.

## 2026-10-30 — A successful review closes stale failure records

- Symptom: `recent failure` / `近期失败` stayed visible after a later review of
  the same objective was answered correctly.
- Cause: `record_quiz_attempt` only graduated an error record when the exact
  same `question_id` was answered correctly. Review generates new question IDs,
  so old active records remained forever and kept `recent_failure`, the +20
  risk and error priority alive.
- Change: an independent correct review of the same knowledge point graduates
  every older `active`/`retrying` error record for that objective. A later
  qualitative pass does the same. Same-question retries keep their existing
  retry history. Hinted answers and non-review answers do not clear unrelated
  errors.
- Files: `upstream/DeepTutor/deeptutor/learning/service.py`.
- Verification: on a copy of the real biochemistry state, a new independent
  correct review changed `active` errors `2 → 0`; non-review and hinted reviews
  left both records active; other objectives were unchanged. Current learning
  data was not modified.
- Package: installer `4 051 248 071` bytes, SHA256
  `962915fd6265d6642b3aaef7436e21a43e014242304e9735b28bcec8caea8955`;
  outer ZIP `DeepSteam-r11.6.8-settings-x64.zip`.

## 2026-10-30 — Installer and package sync for r11.6.8

- Installer payload entries replaced for the two `auth.py` copies and the two
  `learning/service.py` copies; `installer/payload-manifest.json` and the
  installed copy were regenerated.
- Installer self-test: PASS, 184913 files.
- Full payload CRC: 184913/184913 passed.
- Installed-file manifest: 184911/184911 passed before the latest service
  change; the changed service files were then checked against the new manifest.
- Package files: `PACKAGE-STATUS.json` records `repair_3`, `repair_4` and
  `repair_5`; `SHA256SUMS.txt` was regenerated.
- Outer ZIP was rebuilt as `DeepSteam-r11.6.8-settings-x64.zip` and its inner
  installer hash was verified.

## 2026-10-30 — Public source publication r11.6.8

- The public working tree is updated to the `2026.10.19-r11.6-settings`
  source snapshot (package r11.6.8), preserving Git history.
- The snapshot adds 98 files and modifies 133 files relative to the previous
  public tree; no files are removed.
- The three changes above are applied to the snapshot, and this log is added at
  the repository root.
- Release tag: `r11.6.8-settings`.
- Release assets: the 4 GB installer is split into parts smaller than GitHub's
  2 GB per-asset limit, with a join script and checksums; the source ZIP and
  package metadata are attached separately.
- Status: publication commit and release upload are recorded in the next entry
  once they complete.

## 2026-10-31 — Public source and release published

- Source commit `af33394c8c3d504e38e71d6526ff20046b7fb064` pushed to
  `johana425a/mult` `main`.
- Public source manifest re-verified: 11973 files, 0 failures.
- GitHub Release `r11.6.8-settings` published:
  `https://github.com/johana425a/mult/releases/tag/r11.6.8-settings`.
- Release assets verified by GitHub's SHA256 digests:
  - `DeepSteam-Setup-2026.10.19-r11.6-settings-x64.exe.part001`
  - `DeepSteam-Setup-2026.10.19-r11.6-settings-x64.exe.part002`
  - `DeepSteam-Setup-2026.10.19-r11.6-settings-x64.exe.part003`
  - `JOIN-INSTALLER.cmd`
  - `DeepSteam-Source-r11.6-settings.zip`
  - `PACKAGE-STATUS.json`, `SHA256SUMS.txt`, `RELEASE-ASSETS.txt`,
    `RELEASE-NOTES.md` and this log.
- Joined installer SHA256:
  `962915fd6265d6642b3aaef7436e21a43e014242304e9735b28bcec8caea8955`.
- The three-part upload was performed over the direct GitHub route after the
  local proxy proved slower; all three parts report `state=uploaded` and the
  expected sizes.

