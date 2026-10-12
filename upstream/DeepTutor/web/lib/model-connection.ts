export interface ModelConnection {
  selection: 'current' | 'custom' | 'local' | 'native' | 'unconfigured'
  managed: boolean
  provider: string
  provider_label: string
  model: string
  route: 'account' | 'apikey' | 'local' | 'custom' | 'native' | 'unconfigured'
  text: { verified: boolean }
  vision: { verified: boolean }
  targets: { learning: 'selected' | 'not_selected' | 'unavailable'; classroom: 'selected' | 'not_selected' | 'blocked' }
  available?: boolean
  error_code?: string
  message?: string
  embedding?: { status: 'missing' | 'unsupported_chat_gateway' | 'configured_unverified'; available: boolean | null; configured: boolean; verified: boolean; provider: string; model: string; message: string }
  narration: { enabled: boolean; mode: 'local' | 'api'; configured: boolean; provider: string; model: string; voice: string }
}

export interface ClassroomSettings {
  connection_mode?: 'current' | 'custom' | 'local' | 'native' | 'unconfigured'
  selection_required?: string
  model_mode?: 'local' | 'api'
  base_url: string
  model: string
  api_key_set?: boolean
  tts_enabled: boolean
  tts_mode?: 'local' | 'api'
  tts_base_url: string
  tts_model: string
  tts_voice: string
  tts_key_set?: boolean
}

/** Managed transport IDs, URLs and secrets never enter an editable form. */
export function classroomForm(settings: ClassroomSettings, connection: ModelConnection): ClassroomSettings {
  return {
    connection_mode: connection.selection === 'local' ? 'unconfigured' : connection.selection,
    base_url: connection.managed ? '' : settings.base_url || '',
    model: connection.managed ? '' : settings.model || '',
    api_key_set: connection.managed ? false : Boolean(settings.api_key_set),
    tts_enabled: settings.tts_enabled,
    tts_mode: settings.tts_mode || 'local',
    tts_base_url: settings.tts_base_url || '',
    tts_model: settings.tts_model || '',
    tts_voice: settings.tts_voice || '',
    tts_key_set: Boolean(settings.tts_key_set),
  }
}

export function languageSettingsPatch(form: ClassroomSettings, key = '', clear = false): Record<string, unknown> {
  const mode = form.connection_mode || (form.model_mode === 'api' && form.base_url && form.model ? 'custom' : 'unconfigured')
  if (mode === 'local') return { connection_mode: 'unconfigured' }
  if (mode !== 'custom') return { connection_mode: mode }
  return { connection_mode: 'custom', base_url: form.base_url.trim(), model: form.model.trim(), ...(key.trim() ? { api_key: key.trim() } : {}), ...(clear ? { clear_api_key: true } : {}) }
}

export function narrationSettingsPatch(form: ClassroomSettings, key = '', clear = false): Record<string, unknown> {
  return {
    tts_enabled: form.tts_enabled,
    tts_mode: form.tts_mode || 'local',
    ...(form.tts_mode === 'api' ? { tts_base_url: form.tts_base_url.trim(), tts_model: form.tts_model.trim(), tts_voice: form.tts_voice.trim() } : {}),
    ...(key.trim() ? { tts_api_key: key.trim() } : {}),
    ...(clear ? { clear_tts_api_key: true } : {}),
  }
}

export function visibleModelId(model: { model: string; name?: string }, managed: boolean): string {
  return managed && /^dsroute_[A-Za-z0-9_-]+$/.test(model.model) ? model.name || 'Connected model' : model.model
}

