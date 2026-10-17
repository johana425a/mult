/** Only the standalone desktop's top-level classroom can leave its app surface. */
export function deepSteamWorkspaceHref(
  location: Pick<Location, 'protocol' | 'hostname'> & Partial<Pick<Location, 'search'>>,
  topLevel: boolean,
): string | null {
  if (!topLevel || location.protocol !== 'deepsteam:' || location.hostname !== 'classroom') return null;
  const query = new URLSearchParams(location.search || '');
  const workspace = query.get('dt_workspace') ?? query.get('workspace');
  const target = new URL('deepsteam://app/education');
  if (workspace !== null) target.searchParams.set('dt_workspace', workspace);
  return target.toString();
}
