import { apiSuccess } from '@/lib/server/api-response';
import { getWindowsTtsCapability } from '@/lib/server/windows-system-tts';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

/** Metadata only: no synthesis, model call, download, or cloud fallback. */
export async function GET() {
  return apiSuccess({ ...(await getWindowsTtsCapability()) });
}
