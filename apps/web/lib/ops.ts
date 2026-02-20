export function buildDlqJobsPath(limit = 50): string {
  const normalized = Number.isFinite(limit) ? Math.trunc(limit) : 50
  const clamped = Math.max(1, Math.min(200, normalized))
  return `/ops/jobs/dlq?limit=${clamped}`
}

export function buildOpsCollisionGroupsPath(limit = 50): string {
  const normalized = Number.isFinite(limit) ? Math.trunc(limit) : 50
  const clamped = Math.max(1, Math.min(200, normalized))
  return `/ops/messages/collisions?limit=${clamped}`
}

export function buildSyncPausePath(mailboxId: string, minutes = 30): string {
  const normalized = Number.isFinite(minutes) ? Math.trunc(minutes) : 30
  const clamped = Math.max(1, Math.min(10_080, normalized))
  return `/mailboxes/${mailboxId}/sync/pause?minutes=${clamped}`
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

export function formatLagSeconds(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value) || value < 0) return "n/a"
  const seconds = Math.trunc(value)
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) {
    const mins = Math.floor(seconds / 60)
    const rem = seconds % 60
    return rem > 0 ? `${mins}m ${rem}s` : `${mins}m`
  }
  const hours = Math.floor(seconds / 3600)
  const mins = Math.floor((seconds % 3600) / 60)
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`
}
