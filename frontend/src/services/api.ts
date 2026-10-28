import type { ErrorDetail, TokenResponse } from "../types/api";

/**
 * HTTP client for the TeamFlow API.
 *
 * - The access token lives only in memory (never localStorage), so injected scripts can't
 *   read a long-lived credential out of storage. It is lost on reload and restored from the
 *   HttpOnly refresh cookie, which JavaScript cannot read.
 * - On a 401 the client refreshes once and retries. If the refresh fails, the session is
 *   over and `onSessionExpired` is called.
 * - Authorization lives in the backend. Nothing here decides what a user may do.
 */

const BASE = "/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null = null,
    readonly details: ErrorDetail[] = [],
    readonly retryAfter: number | null = null,
  ) {
    super(message);
  }
}

let accessToken: string | null = null;
let refreshInFlight: Promise<string | null> | null = null;
let sessionExpiredHandler: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function hasAccessToken(): boolean {
  return accessToken !== null;
}

export function onSessionExpired(handler: () => void): void {
  sessionExpiredHandler = handler;
}

async function doRefresh(): Promise<string | null> {
  const response = await fetch(`${BASE}/auth/refresh`, {
    method: "POST",
    credentials: "same-origin",
  });
  if (!response.ok) return null;
  const body = (await response.json()) as TokenResponse;
  return body.access_token;
}

/**
 * Exchange the refresh cookie for a new access token. Refresh tokens rotate and the server
 * revokes the whole session if an old one is replayed, so concurrent refreshes must not
 * race: one request at a time within this tab (shared promise), and across tabs via the
 * Web Locks API. The second tab then sends the already-rotated cookie.
 */
export function refreshAccessToken(): Promise<string | null> {
  if (!refreshInFlight) {
    const run = () => doRefresh().catch(() => null);
    const locked =
      typeof navigator !== "undefined" && navigator.locks
        ? navigator.locks.request("teamflow-token-refresh", run)
        : run();
    refreshInFlight = locked.then((token) => {
      accessToken = token;
      return token;
    });
    void refreshInFlight.finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

type Query = Record<string, string | number | boolean | null | undefined>;

interface RequestOptions {
  method?: "GET" | "POST" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Query;
  /** Set false for login/register, which must not trigger a refresh-and-retry. */
  auth?: boolean;
}

function buildUrl(path: string, query?: Query): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  const qs = params.toString();
  return `${BASE}${path}${qs ? `?${qs}` : ""}`;
}

async function toApiError(response: Response): Promise<ApiError> {
  const requestId = response.headers.get("X-Request-ID");
  const retryAfter = Number(response.headers.get("Retry-After")) || null;
  try {
    const body = (await response.json()) as {
      error?: { code: string; message: string; request_id?: string; details?: ErrorDetail[] };
    };
    if (body.error) {
      return new ApiError(
        response.status,
        body.error.code,
        body.error.message,
        body.error.request_id ?? requestId,
        body.error.details ?? [],
        retryAfter,
      );
    }
  } catch {
    // Non-JSON body (e.g. a proxy error page): fall through to a generic error.
  }
  return new ApiError(response.status, "HTTP_ERROR", `Request failed (${response.status}).`, requestId);
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, auth = true } = options;

  const send = (): Promise<Response> => {
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (auth && accessToken) headers.Authorization = `Bearer ${accessToken}`;
    return fetch(buildUrl(path, query), {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "same-origin",
    });
  };

  let response = await send();
  if (response.status === 401 && auth) {
    const token = await refreshAccessToken();
    if (token) {
      response = await send();
    }
    if (response.status === 401) {
      accessToken = null;
      sessionExpiredHandler?.();
    }
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

/** Human-readable message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === "RATE_LIMITED" && error.retryAfter) {
      const minutes = Math.ceil(error.retryAfter / 60);
      return `Too many attempts. Try again in about ${minutes} minute${minutes === 1 ? "" : "s"}.`;
    }
    if (error.code === "VALIDATION_ERROR" && error.details.length > 0) {
      return error.details
        .map((d) => `${(d.field ?? "").replace(/^body\./, "")}: ${d.message ?? "invalid"}`)
        .join(" · ");
    }
    const allowed = error.details[0]?.allowed;
    if (error.code === "INVALID_STATUS_TRANSITION" && allowed) {
      return `${error.message} Allowed next: ${allowed.map((s) => s.replace("_", " ")).join(", ")}.`;
    }
    return error.message;
  }
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}
