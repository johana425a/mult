import { invokeHarnessSurface } from '@/lib/agent/runtime/harness-agent';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
export async function POST(request: Request) { return invokeHarnessSurface(request); }
