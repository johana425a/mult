import type { LLMOption } from './llm-options'

// Display metadata for our owned local gateway profiles. The transport still
// uses its original OpenAI-compatible binding and opaque route/model IDs.
const MANAGED_MODEL_NAMES: Readonly<Record<string, string>> = {
  'deepseek-flash': 'DeepSeek-V4.1-Flash',
  'deepseek-v4-pro': 'DeepSeek-V4-Pro',
}

export function isDesktopManagedOption(option: LLMOption): boolean {
  return option.provider === 'openai'
    && /^dsroute_[A-Za-z0-9_-]+$/.test(option.model)
    && option.profile_id === `deepsteam-harness-${option.model}`
    && option.model_id === option.model
}

export function llmOptionPresentation(option: LLMOption) {
  if (isDesktopManagedOption(option)) {
    const modelName = option.actual_model || (option.model_name && option.model_name !== option.model
      ? option.model_name
      : 'Connected DeepSeek model'
    )
    return {
      provider: 'deepseek',
      providerLabel: 'DeepSeek',
      modelLabel: MANAGED_MODEL_NAMES[modelName] || modelName,
    }
  }
  return {
    provider: option.provider,
    providerLabel: option.provider_label || option.provider || option.profile_name || 'LLM',
    modelLabel: option.actual_model || option.model || option.model_name,
  }
}
