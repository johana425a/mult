/** DeepSteam modification: keep writable classroom state independent of the program directory. */
import path from 'node:path';

/**
 * Resolve writable server data without changing the application's working
 * directory: prompts, built-in skills and other bundled assets still use cwd.
 * Explicit OpenMAIC deployments keep their override; the desktop distribution
 * can move its state root without moving its installed program or models.
 */
export function resolveDataDir(): string {
  if (process.env.OPENMAIC_DATA_DIR) return path.resolve(process.env.OPENMAIC_DATA_DIR);
  if (process.env.DEEPSTEAM_STATE_ROOT) {
    return path.resolve(process.env.DEEPSTEAM_STATE_ROOT, 'runtime', 'openmaic-standalone', 'data');
  }
  return path.resolve(process.cwd(), 'data');
}
