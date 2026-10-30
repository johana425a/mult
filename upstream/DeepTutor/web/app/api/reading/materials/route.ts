import { forwardBackendUpload } from "@/lib/streaming-upload-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// This exact path bypasses the body-cloning Proxy. Both methods retain backend
// workspace/auth checks; neighboring material routes use the regular Proxy.
export function GET(request: Request): Promise<Response> {
  return forwardBackendUpload(request);
}

export function POST(request: Request): Promise<Response> {
  return forwardBackendUpload(request);
}
