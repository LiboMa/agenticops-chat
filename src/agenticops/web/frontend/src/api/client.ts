const BASE_URL = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
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

  if (res.status === 401) {
    // Token expired or invalid — redirect to login
    clearAuthToken();
    if (!window.location.pathname.includes("/login")) {
      window.location.href = "/app/login";
    }
    throw new ApiError(401, "Session expired");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? body.error ?? res.statusText);
  }

  if (res.status === 204) return undefined as T;

  return res.json();
}
