import { NextRequest, NextResponse } from "next/server";

const backendBaseUrl = process.env.NIGHTMARE_API_BASE_URL ?? "http://127.0.0.1:8000";

async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const upstream = new URL(`/api/${path.join("/")}`, backendBaseUrl);
  upstream.search = request.nextUrl.search;
  try {
    const response = await fetch(upstream, {
      method: request.method,
      headers: request.headers.has("content-type") ? { "content-type": request.headers.get("content-type") ?? "application/json" } : undefined,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
      cache: "no-store"
    });
    return new NextResponse(response.body, { status: response.status, headers: { "content-type": response.headers.get("content-type") ?? "application/json" } });
  } catch {
    return NextResponse.json({ detail: `Nightmare Studio API is unavailable at ${backendBaseUrl}` }, { status: 503 });
  }
}

export const GET = proxy;
export const POST = proxy;
export const PATCH = proxy;
