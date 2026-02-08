"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

import { Badge } from "../../../components/ui/badge"
import { Button } from "../../../components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card"
import { Spinner } from "../../../components/ui/spinner"
import { ApiError, apiFetchJson } from "../../../lib/api/client"

type ConnectivityResponse = {
  status: "connected" | "degraded" | "paused" | "disabled"
  profile_email: string | null
  scopes: string[]
  error: string | null
}

function toneForConnectivity(status: ConnectivityResponse["status"]): "green" | "amber" | "red" | "neutral" {
  switch (status) {
    case "connected":
      return "green"
    case "paused":
      return "amber"
    case "degraded":
      return "red"
    case "disabled":
      return "neutral"
    default:
      return "neutral"
  }
}

export function ConnectedClient({ mailboxId }: { mailboxId: string | null }) {
  const connectivity = useQuery({
    queryKey: ["mailboxes", mailboxId, "connectivity"],
    queryFn: async (): Promise<ConnectivityResponse> =>
      apiFetchJson<ConnectivityResponse>(`/mailboxes/${mailboxId}/connectivity`),
    enabled: !!mailboxId,
    retry: false,
    refetchOnWindowFocus: false
  })

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Gmail OAuth Callback</h1>
        <p className="mt-2 text-sm text-neutral-600">
          If you see this page, OAuth redirected back successfully. We’ll verify connectivity next.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Connection Result</CardTitle>
          <CardDescription>Mailbox ID: {mailboxId ?? "missing"}</CardDescription>
        </CardHeader>
        <CardContent>
          {!mailboxId ? (
            <div className="grid gap-3 text-sm text-neutral-700">
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-amber-900">
                No mailbox ID was provided. If you opened this page manually, go back to Mailboxes and
                start the OAuth flow.
              </div>
              <div>
                <Link className="text-neutral-900 underline" href="/mailboxes">
                  Go to Mailboxes
                </Link>
              </div>
            </div>
          ) : connectivity.isLoading ? (
            <div className="flex items-center gap-2 text-sm text-neutral-700">
              <Spinner /> Checking connectivity…
            </div>
          ) : connectivity.isError ? (
            <div className="grid gap-3">
              <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
                {connectivity.error instanceof ApiError
                  ? connectivity.error.detail
                  : "Connectivity check failed"}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button type="button" variant="secondary" onClick={() => connectivity.refetch()}>
                  Retry connectivity check
                </Button>
                <Link className="text-sm text-neutral-900 underline" href="/mailboxes">
                  Back to Mailboxes
                </Link>
              </div>
            </div>
          ) : connectivity.data ? (
            <div className="grid gap-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="text-sm font-medium text-neutral-900">Connectivity</div>
                <Badge tone={toneForConnectivity(connectivity.data.status)}>{connectivity.data.status}</Badge>
              </div>

              <div className="grid gap-1 text-sm text-neutral-700">
                <div>
                  Profile email:{" "}
                  <span className="font-medium text-neutral-900">
                    {connectivity.data.profile_email ?? "unknown"}
                  </span>
                </div>
                <div>
                  Scopes:{" "}
                  {connectivity.data.scopes.length ? (
                    <span className="font-mono text-xs text-neutral-900">
                      {connectivity.data.scopes.join(" ")}
                    </span>
                  ) : (
                    <span className="text-neutral-500">none</span>
                  )}
                </div>
              </div>

              {connectivity.data.error ? (
                <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                  {connectivity.data.error}
                </div>
              ) : null}

              <div className="flex flex-wrap items-center gap-2">
                <Button type="button" variant="secondary" onClick={() => connectivity.refetch()}>
                  Re-check
                </Button>
                <Link className="text-sm text-neutral-900 underline" href="/mailboxes">
                  Back to Mailboxes
                </Link>
              </div>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  )
}

