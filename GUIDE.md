# DeepSteam user and source guide

## Desktop distribution

Keep the installer executable and its matching payload file in the same directory. Run the installer, choose a local installation directory, and open DeepSteam from its shortcut. Internal services are managed by the application. An external browser address is not required for ordinary use.

Open **Connect model** to authorize a supported account or add an API connection. Authorization is completed on the provider's official page. API secrets belong in the dedicated secure input, not in a chat message. A verified connection becomes available to learning and classroom features. Advanced model settings remain available.

The desktop opens one product interface. The internal integration service supplies document, classroom, and learning-record APIs; it does not provide a second standalone workbench. Old portal bookmarks redirect to the main learning interface.

Open a folder from the workspace selector to use local documents. The workspace list manages project entries without recursively deleting the selected folder. Document tools preserve source locations, extracted content, images, and reading progress. Original files remain separate from generated outputs.

The Workspace agent page and the chat page have an access switch. **Full computer** (the default) lets agent tasks, including tasks delegated from learning chats, use other folders and drives and look for relevant material on their own. **Workspace only** keeps file and document tools inside the opened folder. Password stores, browser profiles, and DeepSteam's own settings stay protected at both levels. A change applies from the next task, and each task records the level it ran with.

Scanned pages, formulas, tables, and figures can be parsed by MinerU. It runs entirely on this computer: the MinerU 4.0.12 library, the MinerU2.5-Pro-2605-1.2B model weights, and the official llama.cpp server bound to a loopback address. No MinerU API key, upload, or hosted service is used. By default MinerU uses the `adaptive` tier: the small local models parse every page first, and only pages whose layout shows tables or display formulas are parsed again by the local VLM (`standard` tier). Each result records which tier produced each page and how many tokens the VLM actually processed. Request `standard` (VLM on every page), `advanced` (VLM with image analysis, for figures whose meaning matters) or `basic` (never the VLM) explicitly when needed. On a 4-core CPU the small models take about 4 to 11 seconds per page, while VLM pages take about 13 seconds with a text layer and about 100 seconds when scanned. When the computer has a graphics card, the VLM runs on it through the official Vulkan build of the same llama.cpp release, which handles most desktop and laptop GPUs; software renderers and GPUs with less than 1.5 GB free memory are not used. If the GPU is missing or fails, the CPU build runs the same model, and results name the device used. `scripts/mineru_benchmark.py --devices auto,cpu --save` compares both on this computer and records the faster one. A continued reading keeps the tier its earlier pages used. If the local VLM cannot run for complex pages, they keep the small-model result with a visible warning; no other service is used.

Large batches do not block work. Reading another file never waits behind a MinerU parse: parsing runs in its own lane, one batch at a time, in a worker that keeps the models loaded, and the next batches of a document being read are parsed ahead. A read that needs an unfinished batch returns progress after a short wait (default 25 seconds) instead of waiting for the whole parse. Agents can queue up to 50 documents for background parsing with `prepare_documents` (Harness) or `workspace_document_prepare` (DeepTutor) and check progress with `document_queue`; estimates use speeds measured on this computer. `scripts/mineru_benchmark.py` measures local speed with a PDF you choose. Agents can call `document_engine_status` to confirm the model, weights, and backend in use.

Language models, embedding services, speech services, and image-generation services are configured according to their capabilities. Document parsing can run locally when its runtime and model assets have been installed. There is no bundled chat model and no prepaid cloud API balance.

## Source checkout

1. Install compatible Python and Node.js runtimes.
2. Install the desktop dependencies from `desktop/package-lock.json` using the matching package manager.
3. Install each upstream component's locked dependencies according to its package metadata and English README.
4. Provide the pinned optional document runtime and licensed model assets through the document-runtime staging helpers. These large assets are not stored in this repository.
5. Build the application components, stage the runtime files, and generate a package manifest from the resulting artifacts.
6. Run the installer and document-runtime checks against the exact final package.

The integration scripts use relative project and installation locations, or explicitly supplied settings. Component ports are internal implementation details. New production distributions should keep internal transport encapsulated and should not ship saved credentials or a developer's runtime profile.

## Continue and close

Open the application again to continue persisted conversations, learning records, documents, and tasks. Closing the application stops only the services it owns. A command-line source workflow can use the supplied lifecycle scripts when the necessary runtime has been staged.

## Export and backup

Exported learning records exclude model credentials. A private full backup should be made while the application is closed and should include the selected user-data directory. Keep private backups separate from public source and share packages. Some provider credentials are bound to the operating-system user and must be entered again after migration.

## Uninstall

Use the explicit uninstall entry point in application settings or the installed shortcut. The normal uninstall preserves user data unless the user selects its deletion. The uninstaller checks program ownership and reports progress. It does not recursively delete arbitrary workspace folders.

## Redistribution

Keep the applicable license and attribution files with redistributed code and runtimes. MinerU has additional attribution and commercial-use terms; see `licenses/mineru/MinerU-LICENSE.md`. Keep prepared examples and test fixtures clearly distinguished from actual model-generated teaching content.
