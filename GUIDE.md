# DeepSteam user and source guide

## Desktop distribution

Keep the installer executable and its matching payload file in the same directory. Run the installer, choose a local installation directory, and open DeepSteam from its shortcut. Internal services are managed by the application. An external browser address is not required for ordinary use.

Open **Connect model** to authorize a supported account or add an API connection. Authorization is completed on the provider's official page. API secrets belong in the dedicated secure input, not in a chat message. A verified connection becomes available to learning and classroom features. Advanced model settings remain available.

Open a folder from the workspace selector to use local documents. The workspace list manages project entries without recursively deleting the selected folder. Document tools preserve source locations, extracted content, images, and reading progress. Original files remain separate from generated outputs.

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
