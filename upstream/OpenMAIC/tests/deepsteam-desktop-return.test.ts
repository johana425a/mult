import { describe, expect, it } from 'vitest';
import { deepSteamWorkspaceHref } from '../lib/workbench/deepsteam-desktop-return';

describe('native classroom return', () => {
  it('returns a full-window desktop classroom to the main education workspace', () => {
    expect(deepSteamWorkspaceHref({ protocol: 'deepsteam:', hostname: 'classroom' }, true))
      .toBe('deepsteam://app/education');
  });
  it('does not redirect an iframe or an ordinary website into the desktop host', () => {
    expect(deepSteamWorkspaceHref({ protocol: 'deepsteam:', hostname: 'classroom' }, false)).toBeNull();
    expect(deepSteamWorkspaceHref({ protocol: 'http:', hostname: '127.0.0.1' }, true)).toBeNull();
    expect(deepSteamWorkspaceHref({ protocol: 'deepsteam:', hostname: 'app' }, true)).toBeNull();
  });
  it('preserves explicit workspace scope without accepting a caller-provided return host', () => {
    expect(deepSteamWorkspaceHref({ protocol:'deepsteam:', hostname:'classroom',
      search:'?dt_workspace=ws_test&returnTo=https://example.com' }, true))
      .toBe('deepsteam://app/education?dt_workspace=ws_test');
    expect(deepSteamWorkspaceHref({ protocol:'deepsteam:', hostname:'classroom', search:'?workspace=' }, true))
      .toBe('deepsteam://app/education?dt_workspace=');
  });
});
