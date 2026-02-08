import { buildApiUrl } from "./url"

export class ApiError extends Error {
  status: number
  detail: string

  constructor(status: number, detail: string) {
    super(detail)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
  }
}

async function _readErrorDetail(res: Response): Promise<string> {
  const contentType = res.headers.get("content-type") ?? ""
  if (contentType.includes("application/json")) {
    try {
      const data = (await res.json()) as unknown
      if (data && typeof data === "object" && "detail" in data) {
        const detail = (data as { detail?: unknown }).detail
        if (typeof detail === "string" && detail.trim()) return detail
      }
    } catch {
      // Fall through to text.
    }
  }

  try {
    const text = await res.text()
    if (text.trim()) return text
  } catch {
    // Ignore.
  }

  return `Request failed (${res.status})`
}

export async function apiFetchJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const url = buildApiUrl(path)
  const headers = new Headers(init.headers)
  if (!headers.has("accept")) headers.set("accept", "application/json")

  const hasBody = init.body !== undefined && init.body !== null
  if (hasBody && !headers.has("content-type")) headers.set("content-type", "application/json")

  const res = await fetch(url, {
    ...init,
    headers,
    credentials: "include",
    cache: "no-store"
  })

  if (!res.ok) {
    const detail = await _readErrorDetail(res)
    throw new ApiError(res.status, detail)
  }

  if (res.status === 204) return undefined as unknown as T
  return (await res.json()) as T
}

