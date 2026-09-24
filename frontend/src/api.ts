import type { Job } from "./types";

const TOKEN_KEY = "adpress_token";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: session lasts until reload */
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

function detailMessage(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const loc = Array.isArray(d?.loc) ? d.loc.filter((p: unknown) => p !== "body").join(".") : "";
        return loc ? `${loc}: ${d?.msg}` : d?.msg;
      })
      .join("; ");
  }
  return "Something went wrong.";
}

async function request(method: string, path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Can't reach Adpress. Check your connection.");
  }
  if (!res.ok) {
    let message = `Request failed (${res.status}).`;
    try {
      message = detailMessage((await res.json()).detail);
    } catch {
      /* not JSON */
    }
    if (res.status === 401 && path !== "/auth/login") onUnauthorized();
    throw new ApiError(res.status, message);
  }
  return res;
}

export const api = {
  get: async <T>(path: string) => (await request("GET", path)).json() as Promise<T>,
  post: async <T>(path: string, body?: unknown) => (await request("POST", path, body ?? {})).json() as Promise<T>,
  put: async <T>(path: string, body: unknown) => (await request("PUT", path, body)).json() as Promise<T>,
  patch: async <T>(path: string, body: unknown) => (await request("PATCH", path, body)).json() as Promise<T>,
  del: async <T>(path: string) => (await request("DELETE", path)).json() as Promise<T>,
  /** Fetch a file response and hand it to the browser as a download. */
  download: async (method: "GET" | "POST", path: string, body?: unknown) => {
    const res = await request(method, path, body);
    const disposition = res.headers.get("Content-Disposition") || "";
    const name = /filename="([^"]+)"/.exec(disposition)?.[1] || "download";
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};

/** Poll a background job until it finishes. */
export async function waitForJob(id: string, onUpdate?: (job: Job) => void): Promise<Job> {
  for (;;) {
    const job = await api.get<Job>(`/jobs/${id}`);
    onUpdate?.(job);
    if (job.status === "done" || job.status === "failed") return job;
    await new Promise((r) => setTimeout(r, 1200));
  }
}
