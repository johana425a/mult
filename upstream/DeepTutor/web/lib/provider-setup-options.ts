import type { ProviderSource } from "./provider-registry";
import type { ProviderOption, ServiceName } from "./model-catalog-types";

/** Installed adapters are choices even before an account has been configured.
 * Selecting one only stages its configuration; it never installs a model or
 * claims that a chat login also supports voice, embeddings, search or video.
 */
export function providerSetupOptions(service: ServiceName, options: ProviderOption[]): ProviderSource[] {
  const seen = new Set<string>();
  return options.filter(option => {
    if (!option.value || option.value === "none" || option.auth_mode === "oauth" ||
        option.value === "openai_codex" || option.status === "deprecated" ||
        option.status === "legacy" || seen.has(option.value)) return false;
    seen.add(option.value);
    return true;
  }).map(option => {
    const id = `new-provider:${service}:${option.value}`;
    return { id, ref: { connection_id: id }, name: option.label, provider: option.value,
      service,
      source: { id, name: option.label, provider: option.value, source_service: service,
        api_key: "", base_url: option.base_url || "", api_version: "",
        api_format: "auto" as const } };
  });
}

export function isNewProvider(source: ProviderSource): boolean {
  return source.id.startsWith("new-provider:");
}
