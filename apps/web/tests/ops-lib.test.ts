import { describe, expect, it } from "vitest"

import { buildDlqJobsPath, dlqJobTypeLabel, truncateDetail } from "../lib/ops"

describe("buildDlqJobsPath", () => {
  it("clamps and serializes limit", () => {
    expect(buildDlqJobsPath(80)).toBe("/ops/jobs/dlq?limit=80")
    expect(buildDlqJobsPath(0)).toBe("/ops/jobs/dlq?limit=1")
    expect(buildDlqJobsPath(400)).toBe("/ops/jobs/dlq?limit=200")
  })
})

describe("truncateDetail", () => {
  it("returns compact error details", () => {
    expect(truncateDetail("")).toBe("n/a")
    expect(truncateDetail(null)).toBe("n/a")
    expect(truncateDetail("  parser timeout  ")).toBe("parser timeout")
    expect(truncateDetail("x".repeat(20), 12)).toBe("xxxxxxxxx...")
  })
})

describe("dlqJobTypeLabel", () => {
  it("formats known and unknown job types", () => {
    expect(dlqJobTypeLabel("occurrence_parse")).toBe("Occurrence Parse")
    expect(dlqJobTypeLabel("")).toBe("Unknown")
    expect(dlqJobTypeLabel("custom_type")).toBe("Custom Type")
  })
})
