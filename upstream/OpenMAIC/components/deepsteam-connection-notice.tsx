'use client';

import { useSettingsStore } from '@/lib/store/settings';
import { DEEPSTEAM_SHARED_PROVIDER, deepsteamConnectionLabel } from '@/lib/config/deepsteam-connection';

/** Explain the actual classroom connection and separate narration capabilities. */
export function DeepSteamConnectionNotice({ compact = false }: { compact?: boolean }) {
  const providerId = useSettingsStore(s => s.providerId);
  const connection = useSettingsStore(s => s.deepsteamConnection);
  const error = useSettingsStore(s => s.deepsteamConnectionError);
  const ttsEnabled = useSettingsStore(s => s.ttsEnabled);
  const ttsProviderId = useSettingsStore(s => s.ttsProviderId);
  const ttsConfig = useSettingsStore(s => s.ttsProvidersConfig);
  if (providerId !== DEEPSTEAM_SHARED_PROVIDER) return null;
  return <div className={compact ? 'max-w-72 text-[11px] text-muted-foreground' : 'px-4 pb-3 text-xs text-muted-foreground'} role="status">
    <div>{connection ? deepsteamConnectionLabel(connection) : error || 'Reading the active DeepSteam model…'}</div>
    {!compact && <div className="mt-1 flex flex-wrap items-center gap-2">
      <span>{connection?.text.verified ? 'Text connection verified' : 'Text connection awaits verification'} · {connection?.vision.verified ? 'Image input verified' : connection?.vision.configured ? 'Image input configured (not yet tested)' : 'Image input awaits verification'}</span>
      <span>Narration: {ttsEnabled ? ttsProviderId === 'windows-system-tts' ? 'Local Windows speech' : ttsProviderId === 'browser-native-tts' ? 'Browser speech (video export requires separate configuration)' : 'Separate speech connection' : 'Disabled'}</span>
      {(!ttsEnabled || ttsProviderId === 'browser-native-tts') && ttsConfig['windows-system-tts']?.isServerConfigured &&
        <button type="button" className="underline underline-offset-2" onClick={() => {
          const settings = useSettingsStore.getState();
          settings.setTTSProvider('windows-system-tts'); settings.setTTSVoice('auto-en'); settings.setTTSEnabled(true);
        }}>Enable local narration</button>}
      <span>Image and video generation providers can be selected separately in Settings.</span>
    </div>}
  </div>;
}
