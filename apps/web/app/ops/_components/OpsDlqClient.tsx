"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useState } from "react"

import { Badge } from "../../../components/ui/badge"
import { Button } from "../../../components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card"
import { Spinner } from "../../../components/ui/spinner"
import { ApiError, apiFetchJson } from "../../../lib/api/client"
import { fetchCsrfToken } from "../../../lib/api/csrf"
import { buildDlqJobsPath, dlqJobTypeLabel, truncateDetail } from "../../../lib/ops"

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

function formatDate(value: string): string {
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

export function OpsDlqClient() {
  const qc = useQueryClient()
  const [limit, setLimit] = useState(50)
  const [expandedPayloadId, setExpandedPayloadId] = useState<string | null>(null)
  const [replayError, setReplayError] = useState<string | null>(null)
  const [replayingJobId, setReplayingJobId] = useState<string | null>(null)

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

  const dlqJobs = useQuery({
    queryKey: ["ops-dlq-jobs", limit],
    queryFn: async (): Promise<DlqJobsResponse> => {
      const csrf = await fetchCsrfToken()
      return apiFetchJson<DlqJobsResponse>(buildDlqJobsPath(limit), {
        headers: { "x-csrf-token": csrf }
      })
    },
    enabled: me.data?.role === "admin",
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
    },
    onError: (error) => {
      if (error instanceof ApiError) setReplayError(error.detail)
      else setReplayError("Failed to replay DLQ job")
    },
    onSettled: () => {
      setReplayingJobId(null)
    }
  })

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

  if (me.data.role !== "admin") {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Admin access required</CardTitle>
          <CardDescription>Your current role cannot inspect or replay DLQ jobs.</CardDescription>
        </CardHeader>
      </Card>
    )
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Operations · Dead Letter Queue</CardTitle>
          <CardDescription>
            Review failed jobs and replay specific items after fixing root causes.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <label className="text-sm text-neutral-800">
              <span className="mr-2">Rows</span>
              <select
                value={String(limit)}
                onChange={(event) => setLimit(Number.parseInt(event.target.value, 10))}
                className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-800 outline-none ring-neutral-900/20 transition focus:ring-2"
              >
                <option value="25">25</option>
                <option value="50">50</option>
                <option value="100">100</option>
                <option value="200">200</option>
              </select>
            </label>
            <Button
              type="button"
              variant="secondary"
              onClick={() => dlqJobs.refetch()}
              disabled={dlqJobs.isFetching}
            >
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
        </CardContent>
      </Card>

      {dlqJobs.isLoading ? (
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 text-sm text-neutral-700">
              <Spinner /> Loading failed jobs…
            </div>
          </CardContent>
        </Card>
      ) : null}

      {dlqJobs.isError ? (
        <Card>
          <CardContent className="pt-6">
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              {dlqJobs.error instanceof ApiError ? dlqJobs.error.detail : "Failed to load DLQ jobs"}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {!dlqJobs.isLoading && !dlqJobs.isError && (dlqJobs.data?.items ?? []).length === 0 ? (
        <Card>
          <CardContent className="pt-6 text-sm text-neutral-700">
            No failed jobs in the DLQ for this organization.
          </CardContent>
        </Card>
      ) : null}

      {(dlqJobs.data?.items ?? []).map((job) => (
        <Card key={job.id}>
          <CardContent className="pt-5">
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
                <Button
                  type="button"
                  onClick={() => replayJob.mutate(job.id)}
                  disabled={replayJob.isPending}
                >
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
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
