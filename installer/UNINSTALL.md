# Uninstalling DeepSteam and preserving data

Open **Settings > General > Uninstall DeepSteam** to display the confirmation
window. Opening or canceling that window does not stop the main application or
delete files. The window displays the version, location, and retention options.

The **DeepSteam Learning Agent** entry in Windows **Installed apps**, the
**Uninstall DeepSteam** shortcut in the installation-specific Start menu folder,
and **Uninstall-DeepSteam.exe** open the same confirmation window. Administrator
privileges and the original `.payload.dat` are not required.

Confirming uninstall first closes the desktop and background services belonging
to this installation, then removes registered program files that have not been
modified. It never stops unrelated programs by port number.

Learning records, model connections, imported files, and registered workspaces
are preserved by default. The entire installation directory is not recursively
deleted: new user files, modified program files, and unregistered directories
remain. Reinstall into a new program folder and reconnect preserved data.

**Also remove application records, settings, and cache** is unchecked by default.
Selecting it removes only application data that can be safely identified. Imported
files and workspaces registered through Harness or the native learning service
remain protected. An overlapping data directory may be retained in full.

An external `DeepSteam-Data` directory is eligible for optional cleanup only when
this installation explicitly bound it and its ownership marker matches. Data
owned by another installation and unrelated directories are not automatically
removed or taken over.

Running processes, persistent file locks, altered manifests, unknown workspace
registrations, and linked paths can prevent removal. The application reports the
remaining items and preserves its retry entry. Close the programs using those
files, then retry. Incomplete uninstallation is never reported as complete.

## Installation registration

The installer and uninstaller are compiled from `DeepSteamSetup.cs`. Completing
installation creates a file manifest, unique installation identity, per-user
Windows registration, and Start menu entry. The small installer is copied as
`Uninstall-DeepSteam.exe`.

To rebuild registration for the same full payload, use its matching EXE and
payload file:

```text
DeepSteam-Setup-VERSION-x64.exe --register-uninstall "INSTALL_DIRECTORY"
```

The installed `installer/payload-manifest.json` must match the manifest in the
verified payload. A completion marker alone does not grant deletion authority.
An existing registration is verified before any change; altered manifests are
not overwritten.

## Incremental updates

A program-only update must use `--refresh-uninstall` and a reviewed update receipt,
rather than registering an outdated payload manifest and omitting new files.
The updater must remain outside the installation directory. It does not need
another copy of document models, databases, or the public release package.

The `deepsteam-uninstall-update-v1` receipt binds the installation root, identity,
previous Windows-anchored manifest hash, target version, and updater hash. Its
`files` list contains only reviewed deployed program files with relative paths,
lengths, and hashes. Existing public file ownership, installation identity, and
data roots are retained.

The updater does not scan arbitrary directories to claim ownership. Every
addition or replacement must appear in the reviewed receipt and match the actual
file. Data, credentials, workspaces, escaping paths, and reparse points are
rejected. Unregistered user files and unreviewed changes remain protected.

```text
DeepSteam-Local-Update.exe --check-uninstall-update "INSTALL_DIRECTORY" "RECEIPT.json" "RECEIPT_SHA256" "EXTERNAL_PREFLIGHT_REPORT.json"
DeepSteam-Local-Update.exe --refresh-uninstall "INSTALL_DIRECTORY" "RECEIPT.json" "RECEIPT_SHA256" "EXTERNAL_UPDATE_REPORT.json"
DeepSteam-Local-Update.exe --check-uninstall "INSTALL_DIRECTORY" "EXTERNAL_VERIFICATION_REPORT.json"
```

The first command only checks inputs. The second updates the small launcher,
uninstaller, completion version, merged ownership manifest, and Windows entries.
It neither stops services nor modifies learning data. Failure recovery restores
small entries and registration when possible, without duplicating the program
directory or database. The third command verifies registration and shortcut
targets without uninstalling. Both the process exit status and report `passed`
field must indicate success.

Verify that the Windows entry, uninstall window, and installation marker report
the same version after updating. The installed launch and stop routes rely on
the program and completion marker, rather than requiring the old payload to match
the newly deployed version or reinstalling automatically.

To bind a previously configured external data directory without deleting or
copying data:

```text
DeepSteam.exe --bind-uninstall-data "INSTALL_DIRECTORY" "DEDICATED_DeepSteam-Data_DIRECTORY"
```

This checks `deepsteam-storage.json` and accepts only a dedicated directory named
`DeepSteam-Data`. Never publish `.deepsteam-uninstall-*`, data ownership markers,
or developer Windows registration. Each recipient installation creates its own.

## Verification scope

Installer tests cover path policy, altered manifests, false ownership markers,
same-prefix paths, bounded lock retries, external data ownership, modified file
retention, workspace protection, and directory junctions. Isolated miniature
EXE/payload installations exercise the real WinForms uninstall button with
default retention and optional application data cleanup. They include both
Harness-registered and native database-registered workspaces.

Incremental-update fixtures cover preflight side effects, identity and version
checks, rejection of private paths, retention of previous ownership, and recovery
after update locks. These tests do not uninstall a production installation,
authorize accounts, call real models, or use paid services. Real service shutdown
and deployment checks must be confirmed in the matching integration report.
