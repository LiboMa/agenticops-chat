import { loginPath } from "@/lib/home";

const BASE_URL = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** the contract's UiError code when the server sent one (MVP-2.7.0 S6) */
    public code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function getAuthToken(): string | null {
  return localStorage.getItem("aiops_token");
}

export function setAuthToken(token: string): void {
  localStorage.setItem("aiops_token", token);
}

export function clearAuthToken(): void {
  localStorage.removeItem("aiops_token");
  localStorage.removeItem("aiops_user");
}

const LOC_PREFIXES = new Set(["body", "query", "path"]);

/** A FastAPI error `detail` as one readable line: a string as-is; a 422 list as "field: msg; field: msg"
 *  (field = the `loc` entries after "body"/"query"/"path", joined by "."); any other value as JSON. */
export function formatErrorDetail(detail: unknown): string {
  if (detail === undefined) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item: unknown) => {
        if (item && typeof item === "object" && typeof (item as { msg?: unknown }).msg === "string") {
          const { loc, msg } = item as { loc?: unknown; msg: string };
          const parts = Array.isArray(loc) ? loc.map(String) : [];
          if (parts.length > 0 && LOC_PREFIXES.has(parts[0])) parts.shift();
          return parts.length > 0 ? `${parts.join(".")}: ${msg}` : msg;
        }
        return formatErrorDetail(item);
      })
      .join("; ");
  }
  return JSON.stringify(detail);
}

export async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options?.headers as Record<string, string>),
  };

  // Attach auth token if available
  const token = getAuthToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(url, { ...options, headers });

  // A wrong password is the login endpoint's own 401: say why, don't treat it as an expired session
  if (res.status === 401 && path.startsWith("/auth/login")) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(401, formatErrorDetail(body.detail ?? res.statusText));
  }

  if (res.status === 401) {
    // Token expired or invalid — redirect to login
    clearAuthToken();
    if (!window.location.pathname.includes("/login")) {
      window.location.href = loginPath(window.location);  // log in again, then come back here
    }
    throw new ApiError(401, "Session expired");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, formatErrorDetail(body.detail ?? body.error ?? res.statusText));
  }

  if (res.status === 204) return undefined as T;

  return res.json();
}

/** Download a file the API answers with Content-Disposition (MVP-2.7.0 S6): the Bearer header, never a token in the
 *  URL. A refusal throws ApiError with the server's code (rendering_not_ready, format_unavailable, …). */
export async function apiDownload(path: string): Promise<{ blob: Blob; filename: string | null }> {
  const headers: Record<string, string> = {};
  const token = getAuthToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${BASE_URL}${path}`, { headers });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const d = body?.detail;
    const message = typeof d === "object" && d !== null && "detail" in d ? String(d.detail) : formatErrorDetail(d ?? res.statusText);
    throw new ApiError(res.status, message, typeof d === "object" && d !== null ? (d as { code?: string }).code : undefined);
  }
  const { filenameFromDisposition } = await import("@/lib/download");
  return { blob: await res.blob(), filename: filenameFromDisposition(res.headers.get("Content-Disposition")) };
}
