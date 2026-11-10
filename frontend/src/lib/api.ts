// Local API client: the desktop shell supplies the sidecar URL and its one-time token.
export interface ApiSuccess<T> {
  success: true;
  message: string;
  data: T | null;
}

export interface ApiFailure {
  success: false;
  message: string;
  data: null;
  error: { code: string; details: unknown };
}

export class ApiError extends Error {
  constructor(message: string, public status: number, public code: string, public details: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

interface Backend { url: string; token: string }

// Provided by the Electron preload script; absent when the interface runs in a plain browser.
declare global {
  interface Window { pdfValidation?: { backendInfo(): Promise<Backend> } }
}

let backend: Promise<Backend> | null = null;

function resolveBackend(): Promise<Backend> {
  if (typeof window !== "undefined" && window.pdfValidation) return window.pdfValidation.backendInfo();
  // Plain browser development: run backend/run_server.py yourself and set these variables.
  return Promise.resolve({
    url: process.env.NEXT_PUBLIC_PDF_API_URL || "http://127.0.0.1:8765",
    token: process.env.NEXT_PUBLIC_PDF_API_TOKEN || "",
  });
}

function connection() {
  backend ??= resolveBackend().catch(error => { backend = null; throw error; });
  return backend;
}

// Resolves once the sidecar answers its unauthenticated health check.
export async function waitForBackend(signal: AbortSignal, timeoutMs = 90_000) {
  // A launch failure reported by the shell is final, so it is not retried.
  const { url } = await connection().catch(error => {
    throw new Error(typeof error === "string" ? error : error?.message || "The validation engine did not start.");
  });
  const deadline = Date.now() + timeoutMs;
  let lastError = "The validation engine did not start.";
  while (Date.now() < deadline && !signal.aborted) {
    try {
      const response = await fetch(`${url}/api/health`, { cache: "no-store", signal });
      if (response.ok) return;
      lastError = `The validation engine returned HTTP ${response.status}.`;
    } catch (error) {
      lastError = error instanceof Error ? error.message : lastError;
    }
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  throw new Error(lastError);
}

export const OUTDATED_ENGINE = "The running validation engine does not have this feature yet. Close the app completely and start it again.";

async function responseError(response: Response): Promise<ApiError> {
  // The API never answers 404 for a known route, so a 404 means the engine predates this interface.
  if (response.status === 404) return new ApiError(OUTDATED_ENGINE, 404, "ENGINE_OUTDATED", null);
  try {
    const payload: ApiFailure = await response.json();
    return new ApiError(payload.message || response.statusText, response.status,
      payload.error?.code || "HTTP_ERROR", payload.error?.details ?? null);
  } catch {
    return new ApiError(response.statusText || "Request failed", response.status, "HTTP_ERROR", null);
  }
}

async function send(endpoint: string, options: RequestInit) {
  const { url, token } = await connection();
  return fetch(`${url}/api${endpoint}`, {
    ...options,
    headers: { Authorization: `Bearer ${token}`, ...options.headers },
  });
}

export async function apiRequest<T>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const json = options.body && !(options.body instanceof FormData);
  const response = await send(endpoint, {
    ...options,
    headers: { ...(json ? { "Content-Type": "application/json" } : {}), ...options.headers },
  });
  if (!response.ok) throw await responseError(response);
  if (response.status === 204) return undefined as T;
  const payload: ApiSuccess<T> = await response.json();
  if (payload.success !== true || typeof payload.message !== "string" || !("data" in payload)) {
    throw new Error("Invalid API response");
  }
  return payload.data as T;
}

type ClientDetail = Record<string, string | number | boolean | null>;

let errorEvents = 0;

// Records a user action or interface error in the session logs; never throws or delays the interface.
export function logClientEvent(event: string, detail: ClientDetail = {}, level: "info" | "warning" | "error" = "info",
  channel: "app" | "validation" = "validation") {
  if (level === "error" && ++errorEvents > 25) return; // a render loop must not flood the log
  void apiRequest<void>("/client-events", { method: "POST", body: JSON.stringify({ event, level, channel, detail }) }).catch(() => undefined);
}

export async function apiDownload(endpoint: string, signal?: AbortSignal, options: RequestInit = {}): Promise<Blob> {
  const response = await send(endpoint, { ...options, cache: "no-store", signal });
  if (!response.ok) throw await responseError(response);
  return response.blob();
}
