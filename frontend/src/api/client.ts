// One place for every call to the backend: base URL, auth header, error messages.

// Dev: empty -> same origin, Vite proxies /api to FastAPI. Prod: e.g. https://api.example.com
const BASE_URL = (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, "") ?? "";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public retryAfter?: number,
    public requestId?: string,
  ) {
    super(message);
  }
}

// Set by the auth store; avoids an import cycle between client and store.
let getToken: () => string | null = () => null;
let onUnauthorized: () => void = () => {};
export function configureAuth(tokenGetter: () => string | null, unauthorized: () => void) {
  getToken = tokenGetter;
  onUnauthorized = unauthorized;
}

/** FastAPI errors are {"detail": "text"} or, for validation (422), a list of field errors. */
function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => {
        const field = d.loc?.filter((p) => p !== "body").join(".");
        return field ? `${field}: ${d.msg}` : d.msg;
      })
      .join("; ");
  }
  if (status === 0) return "Can't reach the server. Is the backend running?";
  if (status >= 500) return "Something went wrong on the server. Please try again.";
  return `Request failed (${status})`;
}

type Options = { method?: string; json?: unknown; form?: Record<string, string>; auth?: boolean };

export async function api<T>(path: string, { method = "GET", json, form, auth = true }: Options = {}): Promise<T> {
  const headers: Record<string, string> = {};
  let body: BodyInit | undefined;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) {
    body = new URLSearchParams(form); // OAuth2 login expects form fields
  }
  const token = auth ? getToken() : null;
  if (token) headers.Authorization = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, { method, headers, body });
  } catch {
    throw new ApiError(0, errorMessage(0, null));
  }

  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    // An expired/invalid token on a protected call -> back to the login page.
    if (res.status === 401 && token) onUnauthorized();
    const retry = Number(res.headers.get("Retry-After")) || undefined;
    throw new ApiError(res.status, errorMessage(res.status, data), retry, res.headers.get("X-Request-ID") ?? undefined);
  }
  return data as T;
}
