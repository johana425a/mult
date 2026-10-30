import profile from '../../deeptutor/config/competition-features.json';

// The same checked-in JSON is loaded by the backend and bundled in both the
// client navigation and server proxy. It is not a user permission setting.
export function releasePathAvailable(path: string): boolean {
  let clean: string;
  try { clean = decodeURIComponent(path).split('?')[0].replace(/\/$/, '') || '/'; }
  catch { return false; }
  return !profile.features.some(feature => !feature.enabled &&
    [...feature.pages, ...feature.apis].some(prefix => clean === prefix || clean.startsWith(prefix + '/')));
}

export function releaseFeatureAvailable(id: string): boolean {
  return profile.features.find(feature => feature.id === id)?.enabled === true;
}
