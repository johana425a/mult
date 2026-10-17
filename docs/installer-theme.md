# Native installer and uninstaller theme

The r11.2 maintenance entry uses the same dark colors as the current DeepTutor
interface in `upstream/DeepTutor/web/app/globals.css`. Background, card, text,
muted text, borders, primary actions, secondary actions and destructive states
are aligned. Buttons, progress states, cancellation confirmation and uninstall
warnings share these tokens. The existing gold particle mark and Chinese native
installer labels remain. This change does not implement automatic light/dark
theme switching.

An empty-caption checkbox in the uninstaller now reserves its painted box even
when its label is a separate accessible control. Removal of application records
remains unchecked by default. Enter and Escape in the installation cancellation
dialog continue installation; only the explicit destructive choice cancels it.

## Verification

- The native entry and the offscreen preview helper compile with .NET Framework.
- Nine color mappings were compared against the current CSS tokens.
- Seven actual WinForms control states were rendered without showing a window:
  install, enlarged install, installation failure, uninstall, enlarged uninstall,
  cancellation confirmation and uninstall warning. These are offscreen control
  renders, not screenshots of an interactive native session. Enlargement is a
  layout exercise, not physical multi-monitor DPI certification.
- The installed entry update completed in 18.143 seconds with a durable backup.
  Ownership validation before and after, dry-run receipt validation and the
  ownership refresh all passed. Only three source/identity files and four
  maintenance entry/ownership files were updated. The installer and uninstaller
  match the verified updater bytes; the approved icon is unchanged.
- Desktop processes and the classroom build stayed unchanged. No service restart,
  foreground control, user-data mutation, actual user uninstall or model call was
  performed for this theme update.

The source hash is
`3cc3cd32518e209bee1e75e2dd9fa0f2d915591f19ba593a9bcb1770b16beb47`.
The installed maintenance executable hash is
`07f6f2597ff7c33f773213c08d6aeeb87010356b19f2472dee066b83c34f6a0e`.
The public repository includes source and the preview helper, not that binary.
No new complete distribution installer or desktop/removable-drive archive was
produced. The architecture review evidence remains the separately recorded
r11.1 acceptance; this palette change does not broaden those claims.

`installer/RenderSetupPreview.cs` is compiled with `installer/DeepSteamSetup.cs`
and `/main:DeepSteamInstaller.SetupPreview`. Its only argument is an output
directory. It never calls `Show`, `ShowDialog`, install or uninstall actions.
