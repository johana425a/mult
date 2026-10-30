# Competition candidate: second Windows PC acceptance

Use only the candidate whose installer SHA-256 matches the acceptance request.
This checklist does not certify a release. Save screenshots and recordings locally;
exclude passwords, login QR codes, account tokens and private teaching materials.

1. On the other Windows x64 PC, install into a new short path containing a space
   or Chinese characters. Record the Windows version, installer hash, start and
   finish times. Do not install developer Python or Node to make the test work.
2. Launch normally. Configure the selected model or complete its login in the
   application. Send a message and ask it to read a small file. Check that both
   the answer and the actual tool result appear.
3. Import the supplied nonprivate text PDF and scan sample. Locate the final
   page, ask a source question, switch materials and reopen. Test the agreed
   large book locally; do not add a private book to the distribution archive.
4. Connect Bilibili/YouTube as needed. Check the end of the subtitle transcript,
   playback, subtitle following, seeking, playback speed, fullscreen and exit.
   Ask about the current subtitles and generate the five noncoding question types.
5. Complete one learning session, answer both correctly and incorrectly, save,
   reopen and retrieve the learning record. Wrong answers must not create mastery.
6. Generate a classroom from the sample, edit it, play it, ask a classroom question,
   run its interaction/quiz, save and reopen. Check fullscreen and the retained
   video export. Label a prebuilt demonstration as prebuilt, not live generation.
7. Export MD, Word and PDF from chat, learning, reading and classroom. Download,
   open, change and read back the documents. Also open one XLSX and one PPTX.
8. Repeat core journeys with the configured GPT, DeepSeek Flash and DeepSeek Pro.
   The primary model needs three consecutive passes including cold start and
   reopening. Record provider waiting, tool time and total elapsed time separately.
9. On a disposable test installation, perform the r11.4-to-candidate upgrade.
   Confirm the saved test conversation/material/classroom still opens. Uninstall,
   confirm program files, shortcuts and installer registration are removed, then
   reinstall and reopen the intentionally retained test data. Retained user data
   is not an uninstall defect. Never uninstall the user's working installation.

Run the read-only self-check using the installed bundled Python:

```powershell
& 'D:\DeepSteam Test\runtime\python\python.exe' -I -B 'D:\DeepSteam Test\installer\competition_self_check.py' --app 'D:\DeepSteam Test' --report 'D:\DeepSteam-self-check-01.json'
```

Replace the example path with the actual test installation. The command checks
payload hashes, internal dependency links and document libraries. It does not
log in, open native windows, modify records or uninstall anything. Its report is
supplementary evidence; it cannot replace the observations above or the two-hour
mixed-use run. A failure keeps the candidate unreleased until repaired and retested.
