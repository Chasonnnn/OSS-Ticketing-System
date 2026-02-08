import { describe, expect, it } from "vitest"

import { buildApiUrl } from "../lib/api/url"

describe("buildApiUrl", () => {
  it("joins base + absolute path", () => {
    expect(buildApiUrl("/me", "http://localhost:8000")).toBe("http://localhost:8000/me")
  })

  it("joins base + relative path", () => {
    expect(buildApiUrl("me", "http://localhost:8000")).toBe("http://localhost:8000/me")
  })

  it("handles trailing slash base and query params", () => {
    expect(buildApiUrl("/mailboxes?limit=10", "http://localhost:8000/")).toBe(
      "http://localhost:8000/mailboxes?limit=10"
    )
  })
})

