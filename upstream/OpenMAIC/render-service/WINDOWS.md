# DeepSteam Windows renderer integration

This directory contains the modified OpenMAIC rendering service. It turns an already prepared HTML and audio project into MP4; rendering does not require a language model or a remote speech service. The desktop application manages the internal service connection.

## Local startup

Run these commands from the DeepSteam source root after staging its compatible Python, Node.js, and browser dependencies:

```powershell
python scripts/render_runtime.py bootstrap
python scripts/render_runtime.py start
python scripts/render_runtime.py status
python scripts/render_runtime.py stop
```

Use the Python interpreter selected for the application's runtime. No particular drive letter or developer directory is required. The runtime locates component dependencies through the selected project and installation settings.

`bootstrap` obtains FFmpeg from Gyan, a Windows binary provider linked by <https://ffmpeg.org/download.html>, and verifies the published SHA-256. Its GPLv3 license and accompanying notices remain with the binaries. The dependency report records the downloaded version and hash. Runtime dependencies, caches, render jobs, logs, and temporary browser profiles belong in the selected local data location; they are excluded from this source repository.

The service uses the configured installed browser with the upstream low-memory capture profile: one worker and one rendering job at a time. A compatible Node.js version must satisfy the component's engine requirement. Puppeteer creates its own temporary browser profile instead of reading an existing user login profile.

## Source modifications

- `src/main.ts` binds the rendering service to internal loopback transport.
- `src/runtime-info.ts` reads the Windows browser executable's PE version rather than invoking a version command that might open a browser window. Version-check subprocesses remain hidden.
- `src/resource-profile.ts` accepts the launcher's detected Windows browser version and retains the producer version check.
- `.gitignore` excludes local runtime artifacts.
- `pnpm-lock.yaml` locks the standalone rendering dependency tree separately from the root application.

The render, job status, download, cancellation, preview, and health endpoints remain available to the application. The service is intended for its local backend and is not independently authenticated. The Windows standalone setup does not reproduce Docker's Linux container and firewall isolation. Existing archive bounds, content-security policy, and document hardening remain active. Deploying an external upload service requires its own authentication and isolation configuration.

## Verification and recovery

`scripts/verify-windows-render.py` submits a prepared slide with deterministic animation and Windows system narration to the real rendering service. It checks the resulting video's codecs, dimensions, duration, decoded audio, and distinct rendered frames. This verifies the HTML/audio rendering pipeline; it does not establish the quality of a language model or a speech provider.

Prepared examples are distinct from live model-generated lessons. The upstream job registry is held in memory: completed jobs expire, and restarting the service clears job identifiers. Download completed videos or retain them through the application's persistent classroom export workflow before discarding a rendering job. User data and generated reports are not part of the public source export.
