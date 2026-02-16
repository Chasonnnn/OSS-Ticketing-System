export function buildDlqJobsPath(limit = 50): string {
  const normalized = Number.isFinite(limit) ? Math.trunc(limit) : 50
  const clamped = Math.max(1, Math.min(200, normalized))
  return `/ops/jobs/dlq?limit=${clamped}`
}

export function truncateDetail(value: string | null | undefined, maxLength = 120): string {
  const trimmed = (value || "").trim()
  if (!trimmed) return "n/a"
  if (trimmed.length <= maxLength) return trimmed
  return `${trimmed.slice(0, Math.max(1, maxLength - 3))}...`
}

export function dlqJobTypeLabel(type: string): string {
  const normalized = (type || "").trim()
  if (!normalized) return "Unknown"
  const words = normalized.split("_").map((part) => part.trim()).filter(Boolean)
  if (words.length === 0) return "Unknown"
  return words
    .map((part) => `${part[0].toUpperCase()}${part.slice(1)}`)
    .join(" ")
}
