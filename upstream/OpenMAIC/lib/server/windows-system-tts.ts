/** Real, exportable Windows narration. No browser speech or network provider. */
import { spawn } from 'node:child_process';
import path from 'node:path';

export const WINDOWS_TTS_PROVIDER_ID = 'windows-system-tts' as const;
export const WINDOWS_TTS_MODEL_ID = 'system-speech';
export const WINDOWS_TTS_AUTO_VOICE = 'auto-en';
export const WINDOWS_TTS_MAX_TEXT_LENGTH = 2_000;
const MAX_OUTPUT_BYTES = 32 * 1024 * 1024;
const CAPABILITY_TIMEOUT_MS = 10_000;
const SYNTHESIS_TIMEOUT_MS = 30_000;

export class WindowsTtsError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly httpStatus = 503,
  ) {
    super(message);
    this.name = 'WindowsTtsError';
  }
}

export interface WindowsTtsVoice {
  id: string;
  name: string;
  language: string;
  gender: 'male' | 'female' | 'neutral';
}

export interface WindowsTtsCapability {
  providerId: typeof WINDOWS_TTS_PROVIDER_ID;
  platform: string;
  available: boolean;
  voices: WindowsTtsVoice[];
  defaultVoice: typeof WINDOWS_TTS_AUTO_VOICE | null;
  unavailableReason?: { code: string; message: string };
}

/** Static program only. All voice names and text arrive as JSON on stdin. */
const SPEECH_PROGRAM = String.raw`
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$speaker = $null
$stream = $null
try {
  $request = [Console]::In.ReadToEnd() | ConvertFrom-Json
  Add-Type -AssemblyName System.Speech
  $speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $installed = @($speaker.GetInstalledVoices() | Where-Object { $_.Enabled })
  $voices = @($installed | ForEach-Object {
    $info = $_.VoiceInfo
    @{ id = $info.Name; name = $info.Name; language = $info.Culture.Name; gender = ([string]$info.Gender).ToLowerInvariant() }
  })
  $english = @($installed | Where-Object { $_.VoiceInfo.Culture.TwoLetterISOLanguageName -eq 'en' } | Sort-Object @{Expression={if ($_.VoiceInfo.Culture.Name -eq 'en-US') {0} else {1}}}, @{Expression={if ($_.VoiceInfo.Name -like '*Desktop*') {0} else {1}}}, @{Expression={$_.VoiceInfo.Name}})
  if ($request.operation -eq 'capability') {
    $result = @{ voices = $voices; available = ($english.Count -gt 0) }
  } else {
    if ($english.Count -eq 0) { throw 'LOCAL_TTS_NO_ENGLISH_VOICE' }
    $chosen = $english[0].VoiceInfo
    if ($request.voice -and $request.voice -ne 'auto-en' -and $request.voice -ne 'default') {
      $matches = @($installed | Where-Object { $_.VoiceInfo.Name -eq $request.voice })
      if ($matches.Count -eq 0) { throw 'LOCAL_TTS_VOICE_UNAVAILABLE' }
      $chosen = $matches[0].VoiceInfo
    }
    $speaker.SelectVoice($chosen.Name)
    $speaker.Rate = [int]$request.rate
    $stream = New-Object System.IO.MemoryStream
    $speaker.SetOutputToWaveStream($stream)
    $speaker.Speak([string]$request.text)
    $speaker.SetOutputToNull()
    $result = @{ voiceName = $chosen.Name; base64 = [Convert]::ToBase64String($stream.ToArray()) }
  }
  [Console]::Out.Write(($result | ConvertTo-Json -Depth 6 -Compress))
} catch {
  $code = 'LOCAL_TTS_SYNTHESIS_FAILED'
  if ($_.Exception.Message -like '*LOCAL_TTS_NO_ENGLISH_VOICE*') { $code = 'LOCAL_TTS_NO_ENGLISH_VOICE' }
  if ($_.Exception.Message -like '*LOCAL_TTS_VOICE_UNAVAILABLE*') { $code = 'LOCAL_TTS_VOICE_UNAVAILABLE' }
  [Console]::Out.Write((@{ errorCode = $code } | ConvertTo-Json -Compress))
  exit 1
} finally {
  if ($speaker) { $speaker.Dispose() }
  if ($stream) { $stream.Dispose() }
}
`;

function unavailable(code: string, message: string): WindowsTtsError {
  return new WindowsTtsError(code, message);
}

/** No shell, temporary files, or user-controlled executable/command arguments. */
async function runSpeechProgram(
  input: Record<string, unknown>,
  timeoutMs: number,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  if (process.platform !== 'win32') {
    throw unavailable('LOCAL_TTS_WINDOWS_REQUIRED', 'Local narration requires Windows system speech.');
  }
  signal?.throwIfAborted();
  const systemRoot = process.env.SystemRoot || process.env.SYSTEMROOT || 'C:\\Windows';
  const executable = path.join(
    systemRoot,
    'System32',
    'WindowsPowerShell',
    'v1.0',
    'powershell.exe',
  );
  const encoded = Buffer.from(SPEECH_PROGRAM, 'utf16le').toString('base64');
  return new Promise((resolve, reject) => {
    const child = spawn(executable, ['-NoProfile', '-NonInteractive', '-EncodedCommand', encoded], {
      windowsHide: true,
      shell: false,
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const chunks: Buffer[] = [];
    let outputBytes = 0;
    let settled = false;
    let stopError: unknown;
    const stop = (error: unknown) => {
      if (settled || stopError) return;
      stopError = error;
      // Windows TerminateProcess stops synchronous System.Speech as well.
      child.kill();
    };
    const abort = () => stop(signal?.reason ?? new DOMException('Aborted', 'AbortError'));
    const timeout = setTimeout(
      () => stop(unavailable('LOCAL_TTS_TIMEOUT', 'Local speech synthesis timed out. Shorten this narration segment and retry.')),
      timeoutMs,
    );
    const clean = () => {
      clearTimeout(timeout);
      signal?.removeEventListener('abort', abort);
      child.stdin.destroy();
    };
    const finish = (error?: unknown, value?: Record<string, unknown>) => {
      if (settled) return;
      settled = true;
      clean();
      if (error) reject(error);
      else resolve(value ?? {});
    };
    signal?.addEventListener('abort', abort, { once: true });
    if (signal?.aborted) abort();
    child.stdout.on('data', (chunk: Buffer) => {
      outputBytes += chunk.length;
      if (outputBytes > MAX_OUTPUT_BYTES) {
        stop(unavailable('LOCAL_TTS_OUTPUT_LIMIT', 'The local narration file exceeds the per-segment size limit.'));
        return;
      }
      chunks.push(chunk);
    });
    // Native error text is not returned or logged; it may contain host paths.
    child.stderr.resume();
    child.stdin.on('error', () => {
      stop(unavailable('LOCAL_TTS_PROCESS_FAILED', 'Narration could not be passed to Windows system speech.'));
    });
    child.on('error', () => {
      finish(unavailable('LOCAL_TTS_PROCESS_FAILED', 'Windows system speech could not be started.'));
    });
    child.on('close', (exitCode) => {
      if (stopError) return finish(stopError);
      let result: Record<string, unknown>;
      try {
        result = JSON.parse(
          Buffer.concat(chunks)
            .toString('utf8')
            .replace(/^\uFEFF/, ''),
        );
      } catch {
        return finish(
          unavailable('LOCAL_TTS_INVALID_RESPONSE', 'Windows system speech did not return valid audio.'),
        );
      }
      if (result.errorCode === 'LOCAL_TTS_NO_ENGLISH_VOICE') {
        return finish(
          unavailable(
            'LOCAL_TTS_NO_ENGLISH_VOICE',
            'No English system voice is available on this computer. Install an English Windows voice or select a configured speech service.',
          ),
        );
      }
      if (result.errorCode === 'LOCAL_TTS_VOICE_UNAVAILABLE') {
        return finish(
          unavailable(
            'LOCAL_TTS_VOICE_UNAVAILABLE',
            'The selected system voice is unavailable on this computer. Use automatic selection.',
          ),
        );
      }
      if (exitCode !== 0 || result.errorCode) {
        return finish(
          unavailable(
            'LOCAL_TTS_SYNTHESIS_FAILED',
            'Windows system speech synthesis failed. Check the installed English voices.',
          ),
        );
      }
      finish(undefined, result);
    });
    if (!stopError) child.stdin.end(JSON.stringify(input), 'utf8');
  });
}

/** Verify full PCM framing and measure actual sample duration, never text estimates. */
export function inspectWindowsPcmWav(audio: Uint8Array): {
  durationSeconds: number;
  sampleRate: number;
  channels: number;
  rms: number;
} {
  const bytes = Buffer.from(audio.buffer, audio.byteOffset, audio.byteLength);
  const bad = () =>
    unavailable('LOCAL_TTS_INVALID_AUDIO', 'Local narration is not a complete, audible PCM WAV file.');
  if (
    bytes.length < 44 ||
    bytes.toString('ascii', 0, 4) !== 'RIFF' ||
    bytes.toString('ascii', 8, 12) !== 'WAVE'
  )
    throw bad();
  if (bytes.readUInt32LE(4) + 8 !== bytes.length) throw bad();
  let sampleRate = 0;
  let channels = 0;
  let byteRate = 0;
  let blockAlign = 0;
  let data: Buffer | undefined;
  for (let at = 12; at + 8 <= bytes.length; ) {
    const size = bytes.readUInt32LE(at + 4);
    const start = at + 8;
    if (start + size > bytes.length) throw bad();
    const tag = bytes.toString('ascii', at, at + 4);
    if (tag === 'fmt ') {
      if (size < 16 || bytes.readUInt16LE(start) !== 1 || bytes.readUInt16LE(start + 14) !== 16)
        throw bad();
      channels = bytes.readUInt16LE(start + 2);
      sampleRate = bytes.readUInt32LE(start + 4);
      byteRate = bytes.readUInt32LE(start + 8);
      blockAlign = bytes.readUInt16LE(start + 12);
    }
    if (tag === 'data') data = bytes.subarray(start, start + size);
    at = start + size + (size % 2);
  }
  if (
    !data?.length ||
    !sampleRate ||
    !channels ||
    blockAlign !== channels * 2 ||
    byteRate !== sampleRate * blockAlign ||
    data.length % blockAlign !== 0
  )
    throw bad();
  let sum = 0;
  for (let at = 0; at < data.length; at += 2) sum += bytesSampleSquared(data, at);
  const rms = Math.sqrt(sum / (data.length / 2));
  if (!Number.isFinite(rms) || rms <= 1) throw bad();
  return { durationSeconds: data.length / byteRate, sampleRate, channels, rms };
}

function bytesSampleSquared(data: Buffer, offset: number): number {
  const sample = data.readInt16LE(offset);
  return sample * sample;
}

export async function getWindowsTtsCapability(signal?: AbortSignal): Promise<WindowsTtsCapability> {
  const base = { providerId: WINDOWS_TTS_PROVIDER_ID, platform: process.platform };
  try {
    const result = await runSpeechProgram(
      { operation: 'capability' },
      CAPABILITY_TIMEOUT_MS,
      signal,
    );
    const voices = (Array.isArray(result.voices) ? result.voices : []).flatMap<WindowsTtsVoice>(
      (entry) => {
        if (!entry || typeof entry !== 'object') return [];
        const voice = entry as Record<string, unknown>;
        if (typeof voice.name !== 'string' || typeof voice.language !== 'string') return [];
        return [
          {
            id: voice.name,
            name: voice.name,
            language: voice.language,
            gender: voice.gender === 'male' || voice.gender === 'female' ? voice.gender : 'neutral',
          },
        ];
      },
    );
    const available = voices.some((voice) => /^en(?:-|$)/i.test(voice.language));
    return {
      ...base,
      available,
      voices,
      defaultVoice: available ? WINDOWS_TTS_AUTO_VOICE : null,
      ...(available
        ? {}
        : {
            unavailableReason: {
              code: 'LOCAL_TTS_NO_ENGLISH_VOICE',
              message:
                'No English system voice is available on this computer. Install an English Windows voice or select a configured speech service.',
            },
          }),
    };
  } catch (error) {
    if (signal?.aborted) throw error;
    const failure =
      error instanceof WindowsTtsError
        ? error
        : unavailable('LOCAL_TTS_UNAVAILABLE', 'Local system speech is temporarily unavailable.');
    return {
      ...base,
      available: false,
      voices: [],
      defaultVoice: null,
      unavailableReason: { code: failure.code, message: failure.message },
    };
  }
}

export async function generateWindowsSystemTts(input: {
  text: string;
  voice?: string;
  speed?: number;
  signal?: AbortSignal;
}): Promise<{ audio: Uint8Array; format: 'wav'; durationSeconds: number; voiceName: string }> {
  const text = input.text.trim();
  if (!text || text.length > WINDOWS_TTS_MAX_TEXT_LENGTH)
    throw new WindowsTtsError(
      'LOCAL_TTS_INVALID_TEXT',
      `Each local narration segment must contain 1–${WINDOWS_TTS_MAX_TEXT_LENGTH} characters. Split longer narration into segments.`,
      400,
    );
  if (
    input.speed !== undefined &&
    (!Number.isFinite(input.speed) || input.speed < 0.5 || input.speed > 2)
  )
    throw new WindowsTtsError('LOCAL_TTS_INVALID_SPEED', 'Local narration speed must be between 0.5 and 2.', 400);
  // System.Speech Rate is an integer -10..10. Use its exponential rate scale.
  const rate = Math.max(-10, Math.min(10, Math.round(Math.log2(input.speed ?? 1) * 10)));
  const result = await runSpeechProgram(
    { operation: 'synthesize', text, voice: input.voice || WINDOWS_TTS_AUTO_VOICE, rate },
    SYNTHESIS_TIMEOUT_MS,
    input.signal,
  );
  input.signal?.throwIfAborted();
  if (typeof result.base64 !== 'string' || !/^[A-Za-z0-9+/]*={0,2}$/.test(result.base64))
    throw unavailable('LOCAL_TTS_INVALID_RESPONSE', 'Windows system speech did not return valid audio.');
  const audio = Buffer.from(result.base64, 'base64');
  const { durationSeconds } = inspectWindowsPcmWav(audio);
  return { audio, format: 'wav', durationSeconds, voiceName: String(result.voiceName || '') };
}
