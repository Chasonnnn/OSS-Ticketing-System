type BadgeTone = "neutral" | "green" | "amber" | "red"

export type TicketListFilters = {
  q?: string
  status?: string
  assigneeUserId?: string
  assigneeQueueId?: string
  limit?: number
}

export function buildTicketsPath(filters: TicketListFilters, cursor?: string): string {
  const params = new URLSearchParams()
  const limit = filters.limit && filters.limit > 0 ? Math.min(filters.limit, 100) : 20
  params.set("limit", String(limit))

  const q = filters.q?.trim()
  if (q) params.set("q", q)
  if (filters.status) params.set("status", filters.status)
  if (filters.assigneeUserId) params.set("assignee_user_id", filters.assigneeUserId)
  if (filters.assigneeQueueId) params.set("assignee_queue_id", filters.assigneeQueueId)
  if (cursor) params.set("cursor", cursor)

  return `/tickets?${params.toString()}`
}

export function ticketStatusTone(status: string): BadgeTone {
  switch ((status || "").toLowerCase()) {
    case "new":
    case "open":
    case "resolved":
      return "green"
    case "pending":
      return "amber"
    case "spam":
    case "closed":
      return "red"
    default:
      return "neutral"
  }
}
