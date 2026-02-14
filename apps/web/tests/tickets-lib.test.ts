import { describe, expect, it } from "vitest"

import { buildTicketsPath, ticketStatusTone } from "../lib/tickets"

describe("buildTicketsPath", () => {
  it("builds list query with filters and cursor", () => {
    const path = buildTicketsPath(
      {
        q: "refund",
        status: "open",
        assigneeUserId: "11111111-1111-1111-1111-111111111111",
        assigneeQueueId: "22222222-2222-2222-2222-222222222222",
        limit: 25
      },
      "abc123"
    )
    expect(path).toContain("/tickets?")
    expect(path).toContain("q=refund")
    expect(path).toContain("status=open")
    expect(path).toContain("assignee_user_id=11111111-1111-1111-1111-111111111111")
    expect(path).toContain("assignee_queue_id=22222222-2222-2222-2222-222222222222")
    expect(path).toContain("limit=25")
    expect(path).toContain("cursor=abc123")
  })

  it("omits empty values and uses default limit", () => {
    const path = buildTicketsPath({})
    expect(path).toBe("/tickets?limit=20")
  })
})

describe("ticketStatusTone", () => {
  it("maps status to badge tone", () => {
    expect(ticketStatusTone("open")).toBe("green")
    expect(ticketStatusTone("pending")).toBe("amber")
    expect(ticketStatusTone("spam")).toBe("red")
    expect(ticketStatusTone("something-else")).toBe("neutral")
  })
})
