# Standalone language contract

The Windows standalone competition candidate defaults to Simplified Chinese.
The public source defaults to English when no edition flag is supplied. Both
explicit English and Chinese user preferences remain supported and take
precedence over the default.

Build both web applications with
`NEXT_PUBLIC_DEEPSTEAM_DEFAULT_LANGUAGE=zh`. Record `default_language: zh` in
each component build receipt. The release gate rejects receipts whose language
differs from the Windows release identity. A default cannot be repaired merely
by changing one test browser's local storage.

The standalone Python launcher supplies `DEEPSTEAM_DEFAULT_LANGUAGE=zh` before
loading interface defaults. Saved account choices remain unchanged. The reader
and model-response language settings both retain Chinese options. The original
Chinese translation catalog was restored from the retained standalone source,
with translations added for the current reader and answer-persistence repairs.

Acceptance includes an empty browser profile with an English browser locale,
the default Chinese navigation and classroom, explicit switching to English and
back, and reopening after a selection. Public English defaults are checked
separately. Native foreground interaction is not part of the background test.
