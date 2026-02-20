"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useMemo, useState } from "react"

import { Badge } from "../../../components/ui/badge"
import { Button } from "../../../components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card"
import { Input } from "../../../components/ui/input"
import { Spinner } from "../../../components/ui/spinner"
import { ApiError, apiFetchJson } from "../../../lib/api/client"
import { fetchCsrfToken } from "../../../lib/api/csrf"
import {
  buildDlqJobsPath,
  buildOpsCollisionGroupsPath,
  buildSyncPausePath,
  dlqJobTypeLabel,
  formatLagSeconds,
  truncateDetail,
} from "../../../lib/ops"

type MeResponse = {
  user: { id: string; email: string; display_name: string | null }
  organization: { id: string; name: string; primary_domain: string | null }
  role: string
}

type DlqJobItem = {
  id: string
  type: string
  status: string
  attempts: number
  max_attempts: number
  last_error: string | null
  run_at: string
  updated_at: string
  payload: Record<string, unknown>
}

type DlqJobsResponse = {
  items: DlqJobItem[]
}

type OpsMailboxSyncItem = {
  mailbox_id: string
  email_address: string
  provider: string
  purpose: string
  is_enabled: boolean
  paused_until: string | null
  pause_reason: string | null
  gmail_history_id: number | null
  last_full_sync_at: string | null
  last_incremental_sync_at: string | null
  last_sync_error: string | null
  sync_lag_seconds: number | null
  queued_jobs_by_type: Record<string, number>
  running_jobs_by_type: Record<string, number>
  failed_jobs_last_24h: number
}

type OpsMailboxSyncResponse = {
  items: OpsMailboxSyncItem[]
}

type OpsCollisionGroupItem = {
  collision_group_id: string
  message_count: number
  first_seen_at: string
  last_seen_at: string
  sample_message_ids: string[]
}

type OpsCollisionGroupsResponse = {
  items: OpsCollisionGroupItem[]
}

type OpsMetricsOverviewResponse = {
  queued_jobs: number
  running_jobs: number
  failed_jobs_24h: number
  mailbox_count: number
  paused_mailbox_count: number
  avg_sync_lag_seconds: number | null
}

type RoutingSimulationResponse = {
  allowlisted: boolean
  would_mark_spam: boolean
  matched_rule: { id: string; name: string; priority: number } | null
  applied_actions: {
    assign_queue_id: string | null
    assign_user_id: string | null
    set_status: string | null
    drop: boolean
    auto_close: boolean
  }
  explanation: string
}

type SyncAction = "backfill" | "history" | "pause" | "resume"

function formatDate(value: string | null): string {
  if (!value) return "n/a"
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return "n/a"
  return dt.toLocaleString()
}

function attemptsTone(attempts: number, maxAttempts: number): "neutral" | "amber" | "red" {
  if (maxAttempts <= 0) return "neutral"
  const ratio = attempts / maxAttempts
  if (ratio >= 1) return "red"
  if (ratio >= 0.7) return "amber"
  return "neutral"
}

function statusTone(row: OpsMailboxSyncItem): "green" | "amber" | "red" | "neutral" {
  if (!row.is_enabled) return "neutral"
  if (row.last_sync_error) return "red"
  if (row.paused_until) return "amber"
  if ((row.sync_lag_seconds ?? 0) > 15 * 60) return "amber"
  return "green"
}

function joinJobCounts(input: Record<string, number>): string {
  const entries = Object.entries(input)
  if (entries.length === 0) return "none"
  return entries.map(([jobType, count]) => `${dlqJobTypeLabel(jobType)}:${count}`).join(", ")
}

function actionLabel(action: SyncAction): string {
  switch (action) {
    case "backfill":
      return "Queue Backfill"
    case "history":
      return "Queue History"
    case "pause":
      return "Pause 30m"
    case "resume":
      return "Resume"
  }
}

export function OpsDlqClient() {
  const qc = useQueryClient()
  const [dlqLimit, setDlqLimit] = useState(50)
  const [collisionsLimit, setCollisionsLimit] = useState(50)
  const [expandedPayloadId, setExpandedPayloadId] = useState<string | null>(null)
  const [replayError, setReplayError] = useState<string | null>(null)
  const [replayingJobId, setReplayingJobId] = useState<string | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)
  const [syncBusyMailboxId, setSyncBusyMailboxId] = useState<string | null>(null)
  const [syncBusyAction, setSyncBusyAction] = useState<SyncAction | null>(null)

  const [recipient, setRecipient] = useState("")
  const [senderEmail, setSenderEmail] = useState("")
  const [direction, setDirection] = useState("inbound")
  const [simulationError, setSimulationError] = useState<string | null>(null)
  const [simulationResult, setSimulationResult] = useState<RoutingSimulationResponse | null>(null)

  const me = useQuery({
    queryKey: ["me"],
    queryFn: async (): Promise<MeResponse | null> => {
      try {
        return await apiFetchJson<MeResponse>("/me")
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) return null
        throw error
      }
    },
    retry: false
  })

  const isAdmin = me.data?.role === "admin"

  const dlqJobs = useQuery({
    queryKey: ["ops-dlq-jobs", dlqLimit],
    queryFn: async (): Promise<DlqJobsResponse> => apiFetchJson<DlqJobsResponse>(buildDlqJobsPath(dlqLimit)),
    enabled: isAdmin,
    retry: false
  })

  const syncMailboxes = useQuery({
    queryKey: ["ops-mailboxes-sync"],
    queryFn: async (): Promise<OpsMailboxSyncResponse> => apiFetchJson<OpsMailboxSyncResponse>("/ops/mailboxes/sync"),
    enabled: isAdmin,
    retry: false
  })

  const collisions = useQuery({
    queryKey: ["ops-collisions", collisionsLimit],
    queryFn: async (): Promise<OpsCollisionGroupsResponse> =>
      apiFetchJson<OpsCollisionGroupsResponse>(buildOpsCollisionGroupsPath(collisionsLimit)),
    enabled: isAdmin,
    retry: false
  })

  const metrics = useQuery({
    queryKey: ["ops-metrics"],
    queryFn: async (): Promise<OpsMetricsOverviewResponse> =>
      apiFetchJson<OpsMetricsOverviewResponse>("/ops/metrics/overview"),
    enabled: isAdmin,
    retry: false
  })

  const replayJob = useMutation({
    mutationFn: async (jobId: string): Promise<void> => {
      const csrf = await fetchCsrfToken()
      await apiFetchJson<void>(`/ops/jobs/${jobId}/replay`, {
        method: "POST",
        headers: { "x-csrf-token": csrf }
      })
    },
    onMutate: (jobId) => {
      setReplayingJobId(jobId)
    },
    onSuccess: async () => {
      setReplayError(null)
      await qc.invalidateQueries({ queryKey: ["ops-dlq-jobs"] })
      await qc.invalidateQueries({ queryKey: ["ops-metrics"] })
    },
    onError: (error) => {
      if (error instanceof ApiError) setReplayError(error.detail)
      else setReplayError("Failed to replay DLQ job")
    },
    onSettled: () => {
      setReplayingJobId(null)
    }
  })

  const syncAction = useMutation({
    mutationFn: async ({ mailboxId, action }: { mailboxId: string; action: SyncAction }) => {
      const csrf = await fetchCsrfToken()
      const path =
        action === "backfill"
          ? `/mailboxes/${mailboxId}/sync/backfill`
          : action === "history"
            ? `/mailboxes/${mailboxId}/sync/history`
            : action === "pause"
              ? buildSyncPausePath(mailboxId, 30)
              : `/mailboxes/${mailboxId}/sync/resume`

      return apiFetchJson<Record<string, unknown>>(path, {
        method: "POST",
        headers: { "x-csrf-token": csrf }
      })
    },
    onMutate: ({ mailboxId, action }) => {
      setSyncBusyMailboxId(mailboxId)
      setSyncBusyAction(action)
    },
    onSuccess: async () => {
      setSyncError(null)
      await qc.invalidateQueries({ queryKey: ["ops-mailboxes-sync"] })
      await qc.invalidateQueries({ queryKey: ["ops-metrics"] })
    },
    onError: (error) => {
      if (error instanceof ApiError) setSyncError(error.detail)
      else setSyncError("Failed to run sync action")
    },
    onSettled: () => {
      setSyncBusyMailboxId(null)
      setSyncBusyAction(null)
    }
  })

  const simulateRouting = useMutation({
    mutationFn: async (payload: {
      recipient: string
      senderEmail: string
      direction: string
    }): Promise<RoutingSimulationResponse> => {
      const csrf = await fetchCsrfToken()
      return apiFetchJson<RoutingSimulationResponse>("/tickets/routing/simulate", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({
          recipient: payload.recipient,
          sender_email: payload.senderEmail,
          direction: payload.direction
        })
      })
    },
    onSuccess: (result) => {
      setSimulationError(null)
      setSimulationResult(result)
    },
    onError: (error) => {
      if (error instanceof ApiError) setSimulationError(error.detail)
      else setSimulationError("Failed to simulate routing")
    }
  })

  const mailboxItems = useMemo(() => syncMailboxes.data?.items ?? [], [syncMailboxes.data])

  if (me.isLoading) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center gap-2 text-sm text-neutral-700">
            <Spinner /> Checking session…
          </div>
        </CardContent>
      </Card>
    )
  }

  if (me.data === null) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Sign in required</CardTitle>
          <CardDescription>Use dev login in Mailboxes, then return to the ops dashboard.</CardDescription>
        </CardHeader>
        <CardContent>
          <Link
            href="/mailboxes"
            className="inline-flex h-10 items-center justify-center rounded-lg bg-neutral-900 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-neutral-800 active:bg-neutral-950"
          >
            Open Mailboxes
          </Link>
        </CardContent>
      </Card>
    )
  }

  if (me.isError || !me.data) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
            {me.error instanceof ApiError ? me.error.detail : "Failed to load your session"}
          </div>
        </CardContent>
      </Card>
    )
  }

  if (!isAdmin) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Admin access required</CardTitle>
          <CardDescription>Your current role cannot view operational controls.</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Operations Overview</CardTitle>
          <CardDescription>Core mailbox and queue health in one view.</CardDescription>
        </CardHeader>
        <CardContent>
          {metrics.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-neutral-700">
              <Spinner /> Loading metrics…
            </div>
          ) : metrics.isError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              {metrics.error instanceof ApiError ? metrics.error.detail : "Failed to load metrics"}
            </div>
          ) : metrics.data ? (
            <div className="grid gap-3 md:grid-cols-3">
              <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
                <div className="text-xs uppercase tracking-wide text-neutral-500">Jobs</div>
                <div className="mt-1 text-sm text-neutral-800">
                  queued {metrics.data.queued_jobs} · running {metrics.data.running_jobs}
                </div>
                <div className="text-sm text-neutral-800">failed 24h {metrics.data.failed_jobs_24h}</div>
              </div>
              <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
                <div className="text-xs uppercase tracking-wide text-neutral-500">Mailboxes</div>
                <div className="mt-1 text-sm text-neutral-800">total {metrics.data.mailbox_count}</div>
                <div className="text-sm text-neutral-800">paused {metrics.data.paused_mailbox_count}</div>
              </div>
              <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
                <div className="text-xs uppercase tracking-wide text-neutral-500">Average Sync Lag</div>
                <div className="mt-1 text-sm text-neutral-800">
                  {formatLagSeconds(metrics.data.avg_sync_lag_seconds)}
                </div>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Mailbox Sync Dashboard</CardTitle>
          <CardDescription>Inspect lag, queue pressure, and run sync controls.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="flex items-center gap-2">
            <Button type="button" variant="secondary" onClick={() => syncMailboxes.refetch()} disabled={syncMailboxes.isFetching}>
              {syncMailboxes.isFetching ? (
                <>
                  <Spinner /> Refreshing…
                </>
              ) : (
                "Refresh"
              )}
            </Button>
          </div>
          {syncError ? <div className="text-sm text-red-700">{syncError}</div> : null}

          {syncMailboxes.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-neutral-700">
              <Spinner /> Loading mailbox sync status…
            </div>
          ) : null}

          {syncMailboxes.isError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              {syncMailboxes.error instanceof ApiError
                ? syncMailboxes.error.detail
                : "Failed to load mailbox sync status"}
            </div>
          ) : null}

          {!syncMailboxes.isLoading && !syncMailboxes.isError && mailboxItems.length === 0 ? (
            <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3 text-sm text-neutral-700">
              No mailboxes found in this organization.
            </div>
          ) : null}

          {mailboxItems.map((row) => (
            <div key={row.mailbox_id} className="rounded-lg border border-neutral-200 bg-white p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="grid gap-1">
                  <div className="text-sm font-medium text-neutral-900">{row.email_address}</div>
                  <div className="text-xs text-neutral-500">
                    {row.provider} · {row.purpose} · history {row.gmail_history_id ?? "n/a"}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={statusTone(row)}>
                    {row.paused_until
                      ? "paused"
                      : row.last_sync_error
                        ? "degraded"
                        : row.is_enabled
                          ? "healthy"
                          : "disabled"}
                  </Badge>
                  <Badge tone="neutral">lag {formatLagSeconds(row.sync_lag_seconds)}</Badge>
                </div>
              </div>

              <div className="mt-3 grid gap-1 text-xs text-neutral-700">
                <div>queued: {joinJobCounts(row.queued_jobs_by_type)}</div>
                <div>running: {joinJobCounts(row.running_jobs_by_type)}</div>
                <div>failed 24h: {row.failed_jobs_last_24h}</div>
                <div>last incremental: {formatDate(row.last_incremental_sync_at)}</div>
                <div>last full: {formatDate(row.last_full_sync_at)}</div>
                {row.paused_until ? <div>paused until: {formatDate(row.paused_until)}</div> : null}
                {row.pause_reason ? <div>pause reason: {row.pause_reason}</div> : null}
                {row.last_sync_error ? <div className="text-red-700">last error: {row.last_sync_error}</div> : null}
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                {(["backfill", "history", "pause", "resume"] as SyncAction[]).map((action) => {
                  const isBusy =
                    syncAction.isPending && syncBusyMailboxId === row.mailbox_id && syncBusyAction === action
                  return (
                    <Button
                      key={action}
                      type="button"
                      variant={action === "resume" ? "secondary" : "primary"}
                      disabled={syncAction.isPending}
                      onClick={() => syncAction.mutate({ mailboxId: row.mailbox_id, action })}
                    >
                      {isBusy ? (
                        <>
                          <Spinner /> Working…
                        </>
                      ) : (
                        actionLabel(action)
                      )}
                    </Button>
                  )
                })}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Routing Simulator</CardTitle>
          <CardDescription>Preview allowlist and rule behavior before changing routing config.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <form
            className="grid gap-3 md:grid-cols-[1fr_1fr_180px_auto]"
            onSubmit={(event) => {
              event.preventDefault()
              const r = recipient.trim().toLowerCase()
              const s = senderEmail.trim().toLowerCase()
              if (!r || !s) {
                setSimulationError("Recipient and sender email are required")
                return
              }
              simulateRouting.mutate({ recipient: r, senderEmail: s, direction })
            }}
          >
            <Input
              value={recipient}
              onChange={(event) => setRecipient(event.target.value)}
              placeholder="Recipient (ex: support@example.com)"
            />
            <Input
              value={senderEmail}
              onChange={(event) => setSenderEmail(event.target.value)}
              placeholder="Sender (ex: customer@example.com)"
            />
            <select
              value={direction}
              onChange={(event) => setDirection(event.target.value)}
              className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-800 outline-none ring-neutral-900/20 transition focus:ring-2"
            >
              <option value="inbound">inbound</option>
              <option value="outbound">outbound</option>
            </select>
            <Button type="submit" disabled={simulateRouting.isPending}>
              {simulateRouting.isPending ? (
                <>
                  <Spinner /> Simulating…
                </>
              ) : (
                "Simulate"
              )}
            </Button>
          </form>

          {simulationError ? <div className="text-sm text-red-700">{simulationError}</div> : null}

          {simulationResult ? (
            <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={simulationResult.allowlisted ? "green" : "red"}>
                  {simulationResult.allowlisted ? "allowlisted" : "not allowlisted"}
                </Badge>
                <Badge tone={simulationResult.would_mark_spam ? "red" : "neutral"}>
                  {simulationResult.would_mark_spam ? "would mark spam" : "would not mark spam"}
                </Badge>
              </div>
              <div className="mt-2 text-sm text-neutral-800">{simulationResult.explanation}</div>
              <div className="mt-2 text-xs text-neutral-700">
                matched rule:{" "}
                {simulationResult.matched_rule
                  ? `${simulationResult.matched_rule.name} (priority ${simulationResult.matched_rule.priority})`
                  : "none"}
              </div>
              <pre className="mt-2 overflow-x-auto text-xs text-neutral-700">
                {JSON.stringify(simulationResult.applied_actions, null, 2)}
              </pre>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Dedupe Collision Groups</CardTitle>
          <CardDescription>Inspect canonical-message collision groups for ambiguity debugging.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-sm text-neutral-800">
              <span className="mr-2">Rows</span>
              <select
                value={String(collisionsLimit)}
                onChange={(event) => setCollisionsLimit(Number.parseInt(event.target.value, 10))}
                className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-800 outline-none ring-neutral-900/20 transition focus:ring-2"
              >
                <option value="25">25</option>
                <option value="50">50</option>
                <option value="100">100</option>
                <option value="200">200</option>
              </select>
            </label>
            <Button type="button" variant="secondary" onClick={() => collisions.refetch()} disabled={collisions.isFetching}>
              {collisions.isFetching ? (
                <>
                  <Spinner /> Refreshing…
                </>
              ) : (
                "Refresh"
              )}
            </Button>
          </div>

          {collisions.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-neutral-700">
              <Spinner /> Loading collision groups…
            </div>
          ) : null}

          {collisions.isError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
              {collisions.error instanceof ApiError ? collisions.error.detail : "Failed to load collision groups"}
            </div>
          ) : null}

          {!collisions.isLoading && !collisions.isError && (collisions.data?.items ?? []).length === 0 ? (
            <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3 text-sm text-neutral-700">
              No collision groups found.
            </div>
          ) : null}

          {(collisions.data?.items ?? []).map((group) => (
            <div key={group.collision_group_id} className="rounded-lg border border-neutral-200 bg-white p-3 text-sm">
              <div className="font-medium text-neutral-900">{group.collision_group_id}</div>
              <div className="mt-1 text-xs text-neutral-700">
                messages {group.message_count} · first {formatDate(group.first_seen_at)} · last{" "}
                {formatDate(group.last_seen_at)}
              </div>
              <div className="mt-1 text-xs text-neutral-700">
                samples: {group.sample_message_ids.join(", ") || "none"}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Dead Letter Queue</CardTitle>
          <CardDescription>Review failed jobs and replay specific items after fixing root causes.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-sm text-neutral-800">
              <span className="mr-2">Rows</span>
              <select
                value={String(dlqLimit)}
                onChange={(event) => setDlqLimit(Number.parseInt(event.target.value, 10))}
                className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-800 outline-none ring-neutral-900/20 transition focus:ring-2"
              >
                <option value="25">25</option>
                <option value="50">50</option>
                <option value="100">100</option>
                <option value="200">200</option>
              </select>
            </label>
            <Button type="button" variant="secondary" onClick={() => dlqJobs.refetch()} disabled={dlqJobs.isFetching}>
              {dlqJobs.isFetching ? (
                <>
                  <Spinner /> Refreshing…
                </>
              ) : (
                "Refresh"
              )}
            </Button>
          </div>
          {replayError ? <div className="text-sm text-red-700">{replayError}</div> : null}

          {dlqJobs.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-neutral-700">
              <Spinner /> Loading failed jobs…
            </div>
          ) : null}

          {dlqJobs.isError ? (
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              {dlqJobs.error instanceof ApiError ? dlqJobs.error.detail : "Failed to load DLQ jobs"}
            </div>
          ) : null}

          {!dlqJobs.isLoading && !dlqJobs.isError && (dlqJobs.data?.items ?? []).length === 0 ? (
            <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-3 text-sm text-neutral-700">
              No failed jobs in the DLQ for this organization.
            </div>
          ) : null}

          {(dlqJobs.data?.items ?? []).map((job) => (
            <div key={job.id} className="rounded-lg border border-neutral-200 bg-white p-4">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="grid gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="neutral">{dlqJobTypeLabel(job.type)}</Badge>
                    <Badge tone="red">{job.status.toUpperCase()}</Badge>
                    <Badge tone={attemptsTone(job.attempts, job.max_attempts)}>
                      attempts {job.attempts}/{job.max_attempts}
                    </Badge>
                  </div>
                  <div className="text-sm text-neutral-700">
                    Last error: <span className="font-medium text-neutral-900">{truncateDetail(job.last_error)}</span>
                  </div>
                  <div className="text-xs text-neutral-500">
                    Run at {formatDate(job.run_at)} · Updated {formatDate(job.updated_at)}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    type="button"
                    variant="secondary"
                    onClick={() =>
                      setExpandedPayloadId((current) => (current === job.id ? null : job.id))
                    }
                  >
                    {expandedPayloadId === job.id ? "Hide payload" : "Show payload"}
                  </Button>
                  <Button type="button" onClick={() => replayJob.mutate(job.id)} disabled={replayJob.isPending}>
                    {replayJob.isPending && replayingJobId === job.id ? (
                      <>
                        <Spinner /> Replaying…
                      </>
                    ) : (
                      "Replay"
                    )}
                  </Button>
                </div>
              </div>

              {expandedPayloadId === job.id ? (
                <pre className="mt-3 overflow-x-auto rounded-lg border border-neutral-200 bg-neutral-50 p-3 text-xs text-neutral-700">
                  {JSON.stringify(job.payload, null, 2)}
                </pre>
              ) : null}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
