"use client"

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { useMemo, useState } from "react"

import { Badge } from "../../../components/ui/badge"
import { Button } from "../../../components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../components/ui/card"
import { Input } from "../../../components/ui/input"
import { Spinner } from "../../../components/ui/spinner"
import { fetchCsrfToken } from "../../../lib/api/csrf"
import { ApiError, apiFetchJson } from "../../../lib/api/client"
import { buildTicketsPath, ticketStatusTone, type TicketListFilters } from "../../../lib/tickets"

type MeResponse = {
  user: { id: string; email: string; display_name: string | null }
  organization: { id: string; name: string; primary_domain: string | null }
  role: string
}

type TicketListItem = {
  id: string
  ticket_code: string
  status: string
  priority: string
  subject: string | null
  requester_email: string | null
  requester_name: string | null
  assignee_user_id: string | null
  assignee_queue_id: string | null
  created_at: string
  updated_at: string
  first_message_at: string | null
  last_message_at: string | null
  last_activity_at: string | null
  closed_at: string | null
  stitch_reason: string | null
  stitch_confidence: string
}

type TicketListResponse = {
  items: TicketListItem[]
  next_cursor: string | null
}

type TicketSavedView = {
  id: string
  name: string
  filters: Record<string, unknown>
  is_default: boolean
  created_at: string
  updated_at: string
}

function formatDate(value: string | null): string {
  if (!value) return "n/a"
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return "n/a"
  return dt.toLocaleString()
}

function priorityTone(priority: string): "neutral" | "green" | "amber" | "red" {
  switch ((priority || "").toLowerCase()) {
    case "urgent":
      return "red"
    case "high":
      return "amber"
    case "normal":
      return "green"
    default:
      return "neutral"
  }
}

function asTrimmedString(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined
  const trimmed = value.trim()
  return trimmed ? trimmed : undefined
}

function asLimit(value: unknown): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.max(1, Math.min(100, Math.floor(value)))
  }
  if (typeof value === "string") {
    const parsed = Number.parseInt(value, 10)
    if (Number.isFinite(parsed)) return Math.max(1, Math.min(100, parsed))
  }
  return undefined
}

export function TicketsInboxClient() {
  const qc = useQueryClient()
  const [draftQ, setDraftQ] = useState("")
  const [draftStatus, setDraftStatus] = useState("all")
  const [filters, setFilters] = useState<TicketListFilters>({ limit: 20 })
  const [savedViewId, setSavedViewId] = useState("")
  const [newSavedViewName, setNewSavedViewName] = useState("")
  const [savedViewError, setSavedViewError] = useState<string | null>(null)

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

  const tickets = useInfiniteQuery({
    queryKey: ["tickets", filters],
    queryFn: async ({ pageParam }): Promise<TicketListResponse> => {
      const cursor = typeof pageParam === "string" ? pageParam : undefined
      return apiFetchJson<TicketListResponse>(buildTicketsPath(filters, cursor))
    },
    getNextPageParam: (lastPage) => lastPage.next_cursor ?? undefined,
    initialPageParam: undefined as string | undefined,
    enabled: !!me.data,
    retry: false
  })

  const savedViews = useQuery({
    queryKey: ["ticket-saved-views"],
    queryFn: async (): Promise<TicketSavedView[]> => apiFetchJson<TicketSavedView[]>("/tickets/saved-views"),
    enabled: !!me.data,
    retry: false
  })

  const createSavedView = useMutation({
    mutationFn: async (name: string): Promise<TicketSavedView> => {
      const csrf = await fetchCsrfToken()
      return apiFetchJson<TicketSavedView>("/tickets/saved-views", {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({
          name,
          filters: {
            q: filters.q,
            status: filters.status,
            assignee_user_id: filters.assigneeUserId,
            assignee_queue_id: filters.assigneeQueueId,
            limit: filters.limit
          }
        })
      })
    },
    onSuccess: async (saved) => {
      setSavedViewError(null)
      setNewSavedViewName("")
      setSavedViewId(saved.id)
      await qc.invalidateQueries({ queryKey: ["ticket-saved-views"] })
    },
    onError: (error) => {
      setSavedViewError(error instanceof ApiError ? error.detail : "Failed to save view")
    }
  })

  const deleteSavedView = useMutation({
    mutationFn: async (id: string): Promise<void> => {
      const csrf = await fetchCsrfToken()
      await apiFetchJson<void>(`/tickets/saved-views/${id}`, {
        method: "DELETE",
        headers: { "x-csrf-token": csrf }
      })
    },
    onSuccess: async () => {
      setSavedViewError(null)
      setSavedViewId("")
      await qc.invalidateQueries({ queryKey: ["ticket-saved-views"] })
    },
    onError: (error) => {
      setSavedViewError(error instanceof ApiError ? error.detail : "Failed to delete view")
    }
  })

  const items = useMemo(() => {
    return tickets.data?.pages.flatMap((page) => page.items) ?? []
  }, [tickets.data])

  const canEditSavedViews = me.data?.role === "admin" || me.data?.role === "agent"

  const applySavedView = () => {
    const saved = (savedViews.data ?? []).find((view) => view.id === savedViewId)
    if (!saved) return

    const nextQ = asTrimmedString(saved.filters.q) ?? ""
    const nextStatus = asTrimmedString(saved.filters.status) ?? "all"

    setDraftQ(nextQ)
    setDraftStatus(nextStatus)
    setFilters({
      q: nextQ || undefined,
      status: nextStatus === "all" ? undefined : nextStatus,
      assigneeUserId: asTrimmedString(saved.filters.assignee_user_id),
      assigneeQueueId: asTrimmedString(saved.filters.assignee_queue_id),
      limit: asLimit(saved.filters.limit) ?? 20
    })
  }

  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Ticket Inbox</h1>
        <p className="mt-1 text-sm text-neutral-600">
          Search and triage tickets created by the ingestion and stitching pipeline.
        </p>
      </div>

      {me.isLoading ? (
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center gap-2 text-sm text-neutral-700">
              <Spinner /> Checking session…
            </div>
          </CardContent>
        </Card>
      ) : null}

      {!me.isLoading && me.data === null ? (
        <Card>
          <CardHeader>
            <CardTitle>Sign in required</CardTitle>
            <CardDescription>
              Use dev login in the mailboxes page first, then return here to browse tickets.
            </CardDescription>
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
      ) : null}

      {me.data ? (
        <Card>
          <CardHeader>
            <CardTitle>Filters</CardTitle>
            <CardDescription>Role: {me.data.role}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            <div className="grid gap-3 rounded-lg border border-neutral-200 bg-neutral-50 p-3">
              <div className="text-sm font-medium text-neutral-900">Saved views</div>

              {savedViews.isLoading ? (
                <div className="flex items-center gap-2 text-sm text-neutral-700">
                  <Spinner /> Loading saved views…
                </div>
              ) : (
                <>
                  <div className="grid gap-2 md:grid-cols-[1fr_auto_auto]">
                    <select
                      value={savedViewId}
                      onChange={(event) => setSavedViewId(event.target.value)}
                      className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-800 outline-none ring-neutral-900/20 transition focus:ring-2"
                    >
                      <option value="">Select saved view…</option>
                      {(savedViews.data ?? []).map((view) => (
                        <option key={view.id} value={view.id}>
                          {view.name}
                        </option>
                      ))}
                    </select>
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={applySavedView}
                      disabled={!savedViewId || tickets.isFetching}
                    >
                      Apply view
                    </Button>
                    {canEditSavedViews ? (
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => deleteSavedView.mutate(savedViewId)}
                        disabled={!savedViewId || deleteSavedView.isPending}
                      >
                        {deleteSavedView.isPending ? (
                          <>
                            <Spinner /> Removing…
                          </>
                        ) : (
                          "Delete"
                        )}
                      </Button>
                    ) : null}
                  </div>

                  {canEditSavedViews ? (
                    <div className="grid gap-2 md:grid-cols-[1fr_auto]">
                      <Input
                        value={newSavedViewName}
                        onChange={(event) => setNewSavedViewName(event.target.value)}
                        placeholder="Name this view"
                      />
                      <Button
                        type="button"
                        onClick={() => createSavedView.mutate(newSavedViewName.trim())}
                        disabled={!newSavedViewName.trim() || createSavedView.isPending}
                      >
                        {createSavedView.isPending ? (
                          <>
                            <Spinner /> Saving…
                          </>
                        ) : (
                          "Save current filters"
                        )}
                      </Button>
                    </div>
                  ) : null}
                </>
              )}

              {savedViewError ? <div className="text-sm text-red-700">{savedViewError}</div> : null}
            </div>

            <form
              className="grid gap-3 md:grid-cols-[1fr_220px_auto]"
              onSubmit={(event) => {
                event.preventDefault()
                setFilters({
                  limit: 20,
                  q: draftQ.trim() || undefined,
                  status: draftStatus === "all" ? undefined : draftStatus
                })
              }}
            >
              <Input
                value={draftQ}
                onChange={(event) => setDraftQ(event.target.value)}
                placeholder="Search subject, requester, or ticket code"
              />
              <select
                value={draftStatus}
                onChange={(event) => setDraftStatus(event.target.value)}
                className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-800 outline-none ring-neutral-900/20 transition focus:ring-2"
              >
                <option value="all">All statuses</option>
                <option value="new">New</option>
                <option value="open">Open</option>
                <option value="pending">Pending</option>
                <option value="resolved">Resolved</option>
                <option value="closed">Closed</option>
                <option value="spam">Spam</option>
              </select>
              <Button type="submit" disabled={tickets.isFetching}>
                {tickets.isFetching ? (
                  <>
                    <Spinner /> Applying…
                  </>
                ) : (
                  "Apply"
                )}
              </Button>
            </form>
          </CardContent>
        </Card>
      ) : null}

      {tickets.isError ? (
        <Card>
          <CardContent className="pt-6">
            <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
              {tickets.error instanceof ApiError ? tickets.error.detail : "Failed to load tickets"}
            </div>
          </CardContent>
        </Card>
      ) : null}

      {me.data && !tickets.isError ? (
        <div className="grid gap-3">
          {tickets.isLoading ? (
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center gap-2 text-sm text-neutral-700">
                  <Spinner /> Loading tickets…
                </div>
              </CardContent>
            </Card>
          ) : null}

          {!tickets.isLoading && items.length === 0 ? (
            <Card>
              <CardContent className="pt-6 text-sm text-neutral-700">
                No tickets match the current filters.
              </CardContent>
            </Card>
          ) : null}

          {items.map((ticket) => (
            <Card key={ticket.id}>
              <CardContent className="pt-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div className="grid gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge tone={ticketStatusTone(ticket.status)}>{ticket.status.toUpperCase()}</Badge>
                      <Badge tone={priorityTone(ticket.priority)}>Priority: {ticket.priority}</Badge>
                      <span className="text-xs text-neutral-500">{ticket.ticket_code}</span>
                    </div>
                    <div className="text-base font-medium text-neutral-900">
                      {ticket.subject || "(no subject)"}
                    </div>
                    <div className="text-sm text-neutral-600">
                      From: {ticket.requester_email || "unknown"} · Last activity:{" "}
                      {formatDate(ticket.last_activity_at || ticket.updated_at)}
                    </div>
                  </div>
                  <div>
                    <Link
                      href={`/tickets/${ticket.id}`}
                      className="inline-flex h-9 items-center justify-center rounded-lg bg-neutral-900 px-3 text-sm font-medium text-white shadow-sm transition hover:bg-neutral-800 active:bg-neutral-950"
                    >
                      Open ticket
                    </Link>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}

          {tickets.hasNextPage ? (
            <div>
              <Button
                type="button"
                variant="secondary"
                onClick={() => tickets.fetchNextPage()}
                disabled={tickets.isFetchingNextPage}
              >
                {tickets.isFetchingNextPage ? (
                  <>
                    <Spinner /> Loading more…
                  </>
                ) : (
                  "Load more"
                )}
              </Button>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
