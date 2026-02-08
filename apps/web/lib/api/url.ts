export function getApiBaseUrl(): string {
  // Client components can only see NEXT_PUBLIC_* vars.
  const fromPublic = process.env.NEXT_PUBLIC_API_BASE_URL
  if (fromPublic && fromPublic.trim()) return fromPublic.trim()

  // Server components can also see non-public env vars.
  const fromServer = process.env.API_BASE_URL
  if (fromServer && fromServer.trim()) return fromServer.trim()

  return "http://localhost:8000"
}

export function buildApiUrl(path: string, baseUrl: string = getApiBaseUrl()): string {
  const base = baseUrl.endsWith("/") ? baseUrl : `${baseUrl}/`
  const cleanPath = path.startsWith("/") ? path.slice(1) : path
  return new URL(cleanPath, base).toString()
}

