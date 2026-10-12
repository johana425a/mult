'use client';

import { Box, ExternalLink, Plus } from 'lucide-react';
import { cn } from '@/lib/utils';
import { useI18n } from '@/lib/hooks/use-i18n';
import type { ProviderId, ProviderConfig } from '@/lib/ai/providers';
import { MONO_LOGO_PROVIDERS } from '@/lib/ai/providers';
import { PINNED_PROVIDER_ID, PROVIDER_SIGNUP_LINKS, pickRegionalLink } from './provider-links';

interface ProviderWithServerInfo extends ProviderConfig {
  isServerConfigured?: boolean;
  apiKey?: string;
}

interface ProviderListProps {
  providers: ProviderWithServerInfo[];
  selectedProviderId: ProviderId;
  onSelect: (providerId: ProviderId) => void;
  onAddProvider: () => void;
}

// Language-model provider list in Model services, matching the design.
// model-services-panel uses avatar, name, configuration dot, and outlined selection.
export function ProviderList({
  providers,
  selectedProviderId,
  onSelect,
  onAddProvider,
}: ProviderListProps) {
  const { t, locale } = useI18n();

  // Helper function to get translated provider name
  const getProviderDisplayName = (provider: ProviderConfig) => {
    const translationKey = `settings.providerNames.${provider.id}`;
    const translated = t(translationKey);
    // If translation exists (not equal to key), use it; otherwise fallback to provider.name
    return translated !== translationKey ? translated : provider.name;
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex-1 space-y-1 overflow-y-auto p-1">
        {providers.map((provider) => {
          const configured =
            !!provider.isServerConfigured || !!provider.apiKey || provider.requiresApiKey === false;
          const active = selectedProviderId === provider.id;
          // Promoted providers use an accent outline and the standard darker selected outline,
          // with an API key link at the row end, routed by locale.
          const promoted = provider.id === PINNED_PROVIDER_ID;
          const signupLinks = PROVIDER_SIGNUP_LINKS[provider.id];
          return (
            // External links must be button siblings to avoid nested interactive elements; position them
            // at the row end without forwarding clicks, reserving space in the selection button.
            <div key={provider.id} className="relative">
              <button
                onClick={() => onSelect(provider.id)}
                className={cn(
                  'group flex w-full items-center gap-2.5 rounded-lg px-2 py-1.5 text-left transition-colors',
                  signupLinks && 'pr-8',
                  // Selected state matches ProviderListColumn;
                  // promotional emphasis applies only while unselected.
                  active
                    ? 'bg-background shadow-sm ring-1 ring-border/70'
                    : cn(
                        'hover:bg-background/60',
                        promoted && 'bg-primary/[0.04] ring-1 ring-primary/25',
                      ),
                )}
              >
                <span
                  className={cn(
                    'flex size-7 shrink-0 items-center justify-center overflow-hidden rounded-full transition-colors',
                    active ? 'bg-primary/10 text-primary' : 'bg-muted text-muted-foreground',
                  )}
                >
                  {provider.icon ? (
                    <img
                      src={provider.icon}
                      alt={getProviderDisplayName(provider)}
                      className={cn(
                        'size-4 object-contain',
                        MONO_LOGO_PROVIDERS.has(provider.id) && 'dark:invert',
                      )}
                      onError={(e) => {
                        (e.target as HTMLImageElement).style.display = 'none';
                      }}
                    />
                  ) : (
                    <Box className="size-3.5" />
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span
                    className={cn(
                      'block truncate text-xs leading-tight',
                      active ? 'font-medium text-foreground' : 'text-muted-foreground',
                    )}
                  >
                    {getProviderDisplayName(provider)}
                  </span>
                  <span className="mt-0.5 flex items-center gap-1 text-[10px] text-muted-foreground">
                    <span
                      className={cn(
                        'size-1 rounded-full',
                        configured ? 'bg-emerald-500' : 'bg-muted-foreground/40',
                      )}
                    />
                    {configured
                      ? t('settings.modelServices.configured')
                      : t('settings.modelServices.notConfigured')}
                  </span>
                </span>
              </button>
              {signupLinks && (
                <a
                  href={pickRegionalLink(signupLinks, locale)}
                  target="_blank"
                  rel="noopener noreferrer"
                  aria-label={t('settings.providerLinks.getApiKey')}
                  className="absolute right-2 top-1/2 z-10 -translate-y-1/2 rounded-sm p-1 text-muted-foreground/60 transition-colors hover:bg-muted hover:text-primary focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-primary"
                >
                  <ExternalLink className="size-3.5" />
                </a>
              )}
            </div>
          );
        })}

        {/* Add Provider (ghost row at the end of the list). */}
        <button
          onClick={onAddProvider}
          className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-muted-foreground/70 transition-colors hover:bg-background/60 hover:text-foreground"
        >
          <Plus className="size-3.5" />
          {t('settings.addProviderButton')}
        </button>
      </div>
    </div>
  );
}
