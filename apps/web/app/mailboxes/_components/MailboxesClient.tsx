"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useMemo, useState } from "react"
import { useForm } from "react-hook-form"
import { z } from "zod"

import { Badge } from "../../../components/ui/badge"
import { Button } from "../../../components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card"
import { Input } from "../../../components/ui/input"
import { Spinner } from "../../../components/ui/spinner"
import { fetchCsrfToken } from "../../../lib/api/csrf"
import { ApiError, apiFetchJson } from "../../../lib/api/client"

type MeResponse = {
  user: { id: string; email: string; display_name: string | null }
  organization: { id: string; name: string; primary_domain: string | null }
  role: string
}

type LoginResponse = {
  user: { id: string; email: string; display_name: string | null }
  organization: { id: string; name: string; primary_domain: string | null }
  role: string
  csrf_token: string
}

type MailboxOut = {
  id: string
  purpose: string
  provider: string
  email_address: string
  gmail_profile_email: string | null
  is_enabled: boolean
  created_at: string
  updated_at: string
}

type OAuthStartResponse = { authorization_url: string }

type ConnectivityResponse = {
  status: "connected" | "degraded" | "paused" | "disabled"
  profile_email: string | null
  scopes: string[]
  error: string | null
}

const devLoginSchema = z.object({
  email: z.string().email(),
  organization_name: z.string().min(1).max(200)
})

type DevLoginValues = z.infer<typeof devLoginSchema>

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

export function MailboxesClient() {
  const qc = useQueryClient()
  const [devLoginError, setDevLoginError] = useState<string | null>(null)

  const me = useQuery({
    queryKey: ["me"],
    queryFn: async (): Promise<MeResponse | null> => {
      try {
        return await apiFetchJson<MeResponse>("/me")
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    retry: false
  })

  const mailboxes = useQuery({
    queryKey: ["mailboxes"],
    queryFn: async (): Promise<MailboxOut[]> => apiFetchJson<MailboxOut[]>("/mailboxes"),
    enabled: me.data !== null && me.data !== undefined,
    retry: false
  })

  const journalMailbox = useMemo(() => {
    const list = mailboxes.data ?? []
    return (
      list.find((m) => m.purpose === "journal" && m.provider === "gmail") ??
      list.find((m) => m.purpose === "journal")
    )
  }, [mailboxes.data])

  const connectivity = useQuery({
    queryKey: ["mailboxes", journalMailbox?.id, "connectivity"],
    queryFn: async (): Promise<ConnectivityResponse> =>
      apiFetchJson<ConnectivityResponse>(`/mailboxes/${journalMailbox?.id}/connectivity`),
    enabled: !!journalMailbox?.id && !!me.data,
    retry: false,
    refetchOnWindowFocus: false
  })

  const devLoginForm = useForm<DevLoginValues>({
    defaultValues: {
      email: "admin@example.com",
      organization_name: "Acme Tickets"
    }
  })

  const login = useMutation({
    mutationFn: async (values: DevLoginValues): Promise<LoginResponse> => {
      const csrf = await fetchCsrfToken()
      return apiFetchJson<LoginResponse>("/auth/dev/login", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify(values)
      })
    },
    onSuccess: async () => {
      setDevLoginError(null)
      await qc.invalidateQueries({ queryKey: ["me"] })
      await qc.invalidateQueries({ queryKey: ["mailboxes"] })
    },
    onError: (e: unknown) => {
      if (e instanceof ApiError) setDevLoginError(e.detail)
      else setDevLoginError("Login failed")
    }
  })

  const logout = useMutation({
    mutationFn: async () => {
      const csrf = await fetchCsrfToken()
      return apiFetchJson<{ status: string }>("/auth/logout", {
        method: "POST",
        headers: { "x-csrf-token": csrf }
      })
    },
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: ["me"] })
      await qc.invalidateQueries({ queryKey: ["mailboxes"] })
    }
  })

  const connectJournal = useMutation({
    mutationFn: async (): Promise<OAuthStartResponse> => {
      const csrf = await fetchCsrfToken()
      return apiFetchJson<OAuthStartResponse>("/mailboxes/gmail/journal/oauth/start", {
        method: "POST",
        headers: { "x-csrf-token": csrf }
      })
    },
    onSuccess: (res) => {
      window.location.assign(res.authorization_url)
    }
  })

  const sessionCard = (
    <Card>
      <CardHeader>
        <CardTitle>Session</CardTitle>
        <CardDescription>Authenticate to your org-scoped admin session.</CardDescription>
      </CardHeader>
      <CardContent>
        {me.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-neutral-700">
            <Spinner /> Checking session…
          </div>
        ) : me.data ? (
          <div className="grid gap-4">
            <div className="grid gap-1">
              <div className="text-sm font-medium text-neutral-900">{me.data.user.email}</div>
              <div className="text-sm text-neutral-600">
                Org: <span className="font-medium text-neutral-900">{me.data.organization.name}</span>
                {" · "}
                Role: <span className="font-medium text-neutral-900">{me.data.role}</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                onClick={() => logout.mutate()}
                disabled={logout.isPending}
                type="button"
              >
                {logout.isPending ? (
                  <>
                    <Spinner /> Signing out…
                  </>
                ) : (
                  "Sign out"
                )}
              </Button>
            </div>
          </div>
        ) : (
          <div className="grid gap-4">
            <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-700">
              <div className="font-medium text-neutral-900">Not signed in</div>
              <div className="mt-1">
                Use <span className="font-mono">/auth/dev/login</span> to create a dev session (requires{" "}
                <span className="font-mono">ALLOW_DEV_LOGIN=true</span>).
              </div>
            </div>

            <form
              className="grid gap-3"
              onSubmit={devLoginForm.handleSubmit((values) => {
                const parsed = devLoginSchema.safeParse(values)
                if (!parsed.success) {
                  for (const issue of parsed.error.issues) {
                    const key = issue.path[0]
                    if (key === "email" || key === "organization_name") {
                      devLoginForm.setError(key, { type: "validate", message: issue.message })
                    }
                  }
                  return
                }
                login.mutate(parsed.data)
              })}
            >
              <div className="grid gap-1">
                <label className="text-sm font-medium text-neutral-900" htmlFor="email">
                  Email
                </label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  placeholder="admin@yourdomain.com"
                  {...devLoginForm.register("email")}
                />
                {devLoginForm.formState.errors.email?.message ? (
                  <div className="text-sm text-red-700">{devLoginForm.formState.errors.email.message}</div>
                ) : null}
              </div>

              <div className="grid gap-1">
                <label className="text-sm font-medium text-neutral-900" htmlFor="org">
                  Organization
                </label>
                <Input id="org" placeholder="Your Org Name" {...devLoginForm.register("organization_name")} />
                {devLoginForm.formState.errors.organization_name?.message ? (
                  <div className="text-sm text-red-700">
                    {devLoginForm.formState.errors.organization_name.message}
                  </div>
                ) : null}
              </div>

              {devLoginError ? <div className="text-sm text-red-700">{devLoginError}</div> : null}

              <Button type="submit" disabled={login.isPending}>
                {login.isPending ? (
                  <>
                    <Spinner /> Creating session…
                  </>
                ) : (
                  "Dev login"
                )}
              </Button>
            </form>
          </div>
        )}
      </CardContent>
    </Card>
  )

  const mailboxCard = (
    <Card>
      <CardHeader>
        <CardTitle>Journal Mailbox (Gmail)</CardTitle>
        <CardDescription>
          Connect exactly one journal mailbox per org. We store refresh tokens encrypted at rest.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!me.data ? (
          <div className="text-sm text-neutral-700">
            Sign in first. Then you can start the Google OAuth flow to connect your journal mailbox.
          </div>
        ) : mailboxes.isLoading ? (
          <div className="flex items-center gap-2 text-sm text-neutral-700">
            <Spinner /> Loading mailboxes…
          </div>
        ) : mailboxes.isError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
            {(mailboxes.error as Error).message || "Failed to load mailboxes"}
          </div>
        ) : !journalMailbox ? (
          <div className="grid gap-4">
            <div className="rounded-lg border border-neutral-200 bg-neutral-50 p-4 text-sm text-neutral-700">
              <div className="font-medium text-neutral-900">No journal mailbox connected</div>
              <div className="mt-1">
                This starts OAuth with the required Gmail scope:{" "}
                <span className="font-mono">gmail.readonly</span>.
              </div>
            </div>
            <Button type="button" onClick={() => connectJournal.mutate()} disabled={connectJournal.isPending}>
              {connectJournal.isPending ? (
                <>
                  <Spinner /> Redirecting…
                </>
              ) : (
                "Connect Gmail journal mailbox"
              )}
            </Button>
            {connectJournal.isError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
                {connectJournal.error instanceof ApiError
                  ? connectJournal.error.detail
                  : "Failed to start OAuth"}
              </div>
            ) : null}
          </div>
        ) : (
          <div className="grid gap-4">
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-neutral-200 bg-white p-4">
              <div className="grid gap-1">
                <div className="text-sm font-medium text-neutral-900">{journalMailbox.email_address}</div>
                <div className="text-xs text-neutral-500">
                  Provider: {journalMailbox.provider} · Purpose: {journalMailbox.purpose}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button type="button" variant="secondary" onClick={() => connectJournal.mutate()} disabled={connectJournal.isPending}>
                  {connectJournal.isPending ? (
                    <>
                      <Spinner /> Redirecting…
                    </>
                  ) : (
                    "Reconnect"
                  )}
                </Button>
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => connectivity.refetch()}
                  disabled={connectivity.isFetching}
                >
                  {connectivity.isFetching ? (
                    <>
                      <Spinner /> Checking…
                    </>
                  ) : (
                    "Check connectivity"
                  )}
                </Button>
              </div>
            </div>

            {connectivity.isLoading ? (
              <div className="flex items-center gap-2 text-sm text-neutral-700">
                <Spinner /> Loading connectivity…
              </div>
            ) : connectivity.isError ? (
              <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
                {connectivity.error instanceof ApiError
                  ? connectivity.error.detail
                  : "Failed to check connectivity"}
              </div>
            ) : connectivity.data ? (
              <div className="grid gap-3 rounded-lg border border-neutral-200 bg-neutral-50 p-4">
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
              </div>
            ) : null}

            <div className="text-xs text-neutral-500">
              OAuth callback returns JSON for API clients, and redirects browsers to{" "}
              <span className="font-mono">/mailboxes/connected</span>.
            </div>
          </div>
        )}

        <div className="mt-6 border-t border-neutral-200 pt-4 text-sm text-neutral-600">
          Need help? See <Link className="text-neutral-900 underline" href="/mailboxes/connected">the callback page</Link>.
        </div>
      </CardContent>
    </Card>
  )

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Mailbox Connections</h1>
        <p className="mt-2 text-sm text-neutral-600">
          Admin-only. All data is scoped by <span className="font-mono">organization_id</span>.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {sessionCard}
        {mailboxCard}
      </div>
    </div>
  )
}

