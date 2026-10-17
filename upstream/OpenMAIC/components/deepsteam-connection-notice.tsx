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
    <div>{connection ? deepsteamConnectionLabel(connection) : error || '正在读取 DeepSteam 当前模型…'}</div>
    {!compact && <div className="mt-1 flex flex-wrap items-center gap-2">
      <span>{connection?.text.verified ? '文本连接已验证' : '文本连接待实际验证'} · {connection?.vision.verified ? '图片输入已验证' : connection?.vision.configured ? '图片输入已配置（待实测）' : '图片输入待验证'}</span>
      <span>旁白：{ttsEnabled ? ttsProviderId === 'windows-system-tts' ? '本机 Windows 语音' : ttsProviderId === 'browser-native-tts' ? '浏览器语音（视频导出需独立配置）' : '独立语音接口' : '未启用'}</span>
      {(!ttsEnabled || ttsProviderId === 'browser-native-tts') && ttsConfig['windows-system-tts']?.isServerConfigured &&
        <button type="button" className="underline underline-offset-2" onClick={() => {
          const settings = useSettingsStore.getState();
          settings.setTTSProvider('windows-system-tts'); settings.setTTSVoice('auto-zh'); settings.setTTSEnabled(true);
        }}>启用本机旁白</button>}
      <span>图像／视频生成接口可在设置中单独选择。</span>
    </div>}
  </div>;
}
