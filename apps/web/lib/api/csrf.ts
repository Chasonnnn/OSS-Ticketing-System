import { apiFetchJson } from "./client"

export async function fetchCsrfToken(): Promise<string> {
  const res = await apiFetchJson<{ csrf_token: string }>("/auth/csrf")
  return res.csrf_token
}

