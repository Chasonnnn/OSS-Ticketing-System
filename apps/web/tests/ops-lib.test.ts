import { describe, expect, it } from "vitest"

import {
  buildDlqJobsPath,
  buildOpsCollisionGroupsPath,
  buildSyncPausePath,
  dlqJobTypeLabel,
  formatLagSeconds,
  truncateDetail,
} from "../lib/ops"

describe("buildDlqJobsPath", () => {
  it("clamps and serializes limit", () => {
    expect(buildDlqJobsPath(80)).toBe("/ops/jobs/dlq?limit=80")
    expect(buildDlqJobsPath(0)).toBe("/ops/jobs/dlq?limit=1")
    expect(buildDlqJobsPath(400)).toBe("/ops/jobs/dlq?limit=200")
  })
})

describe("buildOpsCollisionGroupsPath", () => {
  it("clamps and serializes limit", () => {
    expect(buildOpsCollisionGroupsPath(25)).toBe("/ops/messages/collisions?limit=25")
    expect(buildOpsCollisionGroupsPath(-1)).toBe("/ops/messages/collisions?limit=1")
    expect(buildOpsCollisionGroupsPath(300)).toBe("/ops/messages/collisions?limit=200")
  })
})

describe("buildSyncPausePath", () => {
  it("builds pause URLs with bounded minute values", () => {
    expect(buildSyncPausePath("mailbox-1", 30)).toBe("/mailboxes/mailbox-1/sync/pause?minutes=30")
    expect(buildSyncPausePath("mailbox-1", 0)).toBe("/mailboxes/mailbox-1/sync/pause?minutes=1")
    expect(buildSyncPausePath("mailbox-1", 20_000)).toBe(
      "/mailboxes/mailbox-1/sync/pause?minutes=10080"
    )
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

describe("formatLagSeconds", () => {
  it("renders sync lag in readable units", () => {
    expect(formatLagSeconds(null)).toBe("n/a")
    expect(formatLagSeconds(45)).toBe("45s")
    expect(formatLagSeconds(75)).toBe("1m 15s")
    expect(formatLagSeconds(3720)).toBe("1h 2m")
  })
})
