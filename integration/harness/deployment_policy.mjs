/** DeepSteam maintenance policy: editable program files, private live state. */
import { dirname, join } from 'node:path';

export function deploymentProtectedPaths(programRoot, stateRoot, tokenFile) {
  const state = stateRoot || programRoot;
  const home = join(state, 'runtime', 'deeptutor-home', 'data');
  return [dirname(tokenFile), join(home, 'system'), join(home, 'user', 'private'),
    join(home, 'user', 'settings'), join(state, 'runtime', 'desktop-profile'),
    join(state, 'cache', 'desktop-session')];
}

export function routeSupportsImages(route) {
  return route?.vision_verified === true || route?.vision_supported === true
    || route?.resolved_model?.capabilities?.vision === true;
}
