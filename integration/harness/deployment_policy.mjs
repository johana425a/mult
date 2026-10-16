/** DeepSteam maintenance policy: editable program files, private live state. */
import { dirname, join } from 'node:path';

export function deploymentProtectedPaths(programRoot, stateRoot, tokenFile) {
  const state = stateRoot || programRoot;
  return [dirname(tokenFile), join(state, 'runtime', 'deeptutor-home'), join(state, 'data')];
}

export function routeSupportsImages(route) {
  return route?.vision_verified === true || route?.vision_supported === true
    || route?.resolved_model?.capabilities?.vision === true;
}
