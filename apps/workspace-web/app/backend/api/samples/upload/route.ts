import { proxySampleUpload } from "@/lib/upload-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

// A concrete route takes precedence over /backend/:path* external rewrites.
export const POST = proxySampleUpload;
