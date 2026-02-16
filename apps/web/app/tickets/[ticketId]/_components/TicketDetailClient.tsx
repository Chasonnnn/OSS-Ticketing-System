"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import Link from "next/link"
import { FormEvent, useMemo, useState } from "react"

import { Badge } from "../../../../components/ui/badge"
import { Button } from "../../../../components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../../components/ui/card"
import { Input } from "../../../../components/ui/input"
import { Spinner } from "../../../../components/ui/spinner"
import { ApiError, apiFetchJson } from "../../../../lib/api/client"
import { fetchCsrfToken } from "../../../../lib/api/csrf"
import { buildApiUrl } from "../../../../lib/api/url"
import { ticketStatusTone } from "../../../../lib/tickets"

type MeResponse = {
  user: { id: string; email: string; display_name: string | null }
  organization: { id: string; name: string; primary_domain: string | null }
  role: string
}

type TicketAttachment = {
  id: string
  filename: string | null
  content_type: string | null
  size_bytes: number
  is_inline: boolean
  content_id: string | null
}

type TicketMessage = {
  message_id: string
  collision_group_id: string | null
  stitched_at: string
  stitch_reason: string
  stitch_confidence: string
  direction: string
  rfc_message_id: string | null
  date_header: string | null
  subject: string | null
  from_email: string | null
  to_emails: string[]
  cc_emails: string[]
  snippet: string | null
  body_text: string | null
  body_html_sanitized: string | null
  attachments: TicketAttachment[]
  occurrences: {
    id: string
    mailbox_id: string
    gmail_message_id: string
    state: string
    original_recipient: string | null
    original_recipient_source: string
    original_recipient_confidence: string
    original_recipient_evidence: Record<string, unknown>
    routed_at: string | null
    parse_error: string | null
    stitch_error: string | null
    route_error: string | null
  }[]
}

type TicketEvent = {
  id: string
  actor_user_id: string | null
  event_type: string
  created_at: string
  event_data: Record<string, unknown>
}

type TicketNote = {
  id: string
  author_user_id: string | null
  body_markdown: string
  body_html_sanitized: string | null
  created_at: string
  updated_at: string
}

type TicketDetailResponse = {
  ticket: {
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
  messages: TicketMessage[]
  events: TicketEvent[]
  notes: TicketNote[]
}

type QueueOut = {
  id: string
  name: string
  slug: string
  created_at: string
}

type SendIdentityOut = {
  id: string
  mailbox_id: string
  from_email: string
  from_name: string | null
  status: string
  is_enabled: boolean
  created_at: string
  updated_at: string
}

type TicketReplyResponse = {
  status: string
  job_id: string
  message_id: string
  oss_message_id: string
}

function formatDate(value: string | null): string {
  if (!value) return "n/a"
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return "n/a"
  return dt.toLocaleString()
}

function parseEmailCsv(value: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const part of value.split(",")) {
    const email = part.trim().toLowerCase()
    if (!email || seen.has(email)) continue
    seen.add(email)
    out.push(email)
  }
  return out
}

function defaultReplySubject(ticketSubject: string | null): string {
  const subject = (ticketSubject || "").trim()
  if (!subject) return "Re: (no subject)"
  return /^re\s*:/i.test(subject) ? subject : `Re: ${subject}`
}

export function TicketDetailClient({ ticketId }: { ticketId: string }) {
  const qc = useQueryClient()
  const [assignmentMode, setAssignmentMode] = useState<"keep" | "clear" | "queue">("keep")
  const [controlError, setControlError] = useState<string | null>(null)
  const [noteBody, setNoteBody] = useState("")
  const [noteError, setNoteError] = useState<string | null>(null)

  const [replyIdentityId, setReplyIdentityId] = useState("")
  const [replyIdentityDirty, setReplyIdentityDirty] = useState(false)
  const [replyTo, setReplyTo] = useState("")
  const [replyCc, setReplyCc] = useState("")
  const [replySubject, setReplySubject] = useState("")
  const [replySubjectDirty, setReplySubjectDirty] = useState(false)
  const [replyBody, setReplyBody] = useState("")
  const [replyError, setReplyError] = useState<string | null>(null)
  const [replyQueuedMessage, setReplyQueuedMessage] = useState<string | null>(null)

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

  const detail = useQuery({
    queryKey: ["ticket", ticketId],
    queryFn: async (): Promise<TicketDetailResponse> =>
      apiFetchJson<TicketDetailResponse>(`/tickets/${ticketId}`),
    enabled: !!me.data,
    retry: false
  })

  const queues = useQuery({
    queryKey: ["queues"],
    queryFn: async (): Promise<QueueOut[]> => apiFetchJson<QueueOut[]>("/queues"),
    enabled: !!me.data,
    retry: false
  })

  const sendIdentities = useQuery({
    queryKey: ["ticket-send-identities"],
    queryFn: async (): Promise<SendIdentityOut[]> => apiFetchJson<SendIdentityOut[]>("/tickets/send-identities"),
    enabled: !!me.data && me.data.role !== "viewer",
    retry: false
  })

  const updateTicket = useMutation({
    mutationFn: async ({
      status,
      priority,
      assignmentMode,
      queueId
    }: {
      status: string
      priority: string
      assignmentMode: "keep" | "clear" | "queue"
      queueId?: string
    }) => {
      const csrf = await fetchCsrfToken()
      const payload: Record<string, string | null> = {
        status,
        priority
      }
      if (assignmentMode === "clear") {
        payload.assignee_queue_id = null
      } else if (assignmentMode === "queue") {
        payload.assignee_queue_id = queueId ?? null
      }
      return apiFetchJson(`/tickets/${ticketId}`, {
        method: "PATCH",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify(payload)
      })
    },
    onSuccess: async () => {
      setControlError(null)
      await qc.invalidateQueries({ queryKey: ["ticket", ticketId] })
      await qc.invalidateQueries({ queryKey: ["tickets"] })
    },
    onError: (error) => {
      if (error instanceof ApiError) setControlError(error.detail)
      else setControlError("Failed to update ticket")
    }
  })

  const createNote = useMutation({
    mutationFn: async (bodyMarkdown: string) => {
      const csrf = await fetchCsrfToken()
      return apiFetchJson(`/tickets/${ticketId}/notes`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({ body_markdown: bodyMarkdown })
      })
    },
    onSuccess: async () => {
      setNoteError(null)
      setNoteBody("")
      await qc.invalidateQueries({ queryKey: ["ticket", ticketId] })
      await qc.invalidateQueries({ queryKey: ["tickets"] })
    },
    onError: (error) => {
      if (error instanceof ApiError) setNoteError(error.detail)
      else setNoteError("Failed to create note")
    }
  })

  const queueReply = useMutation({
    mutationFn: async (payload: {
      sendIdentityId: string
      toEmails: string[]
      ccEmails: string[]
      subject: string
      bodyText: string
    }): Promise<TicketReplyResponse> => {
      const csrf = await fetchCsrfToken()
      return apiFetchJson<TicketReplyResponse>(`/tickets/${ticketId}/reply`, {
        method: "POST",
        headers: { "x-csrf-token": csrf },
        body: JSON.stringify({
          send_identity_id: payload.sendIdentityId,
          to_emails: payload.toEmails,
          cc_emails: payload.ccEmails,
          subject: payload.subject,
          body_text: payload.bodyText,
        })
      })
    },
    onSuccess: async (queued) => {
      setReplyError(null)
      setReplyQueuedMessage(`Queued message ${queued.message_id}`)
      setReplyBody("")
      await qc.invalidateQueries({ queryKey: ["ticket", ticketId] })
      await qc.invalidateQueries({ queryKey: ["tickets"] })
    },
    onError: (error) => {
      if (error instanceof ApiError) setReplyError(error.detail)
      else setReplyError("Failed to queue reply")
    }
  })

  const preferredFrom = useMemo(() => {
    const first = (sendIdentities.data ?? [])[0]
    if (!first) return ""
    return first.from_name ? `${first.from_name} <${first.from_email}>` : first.from_email
  }, [sendIdentities.data])

  const selectedReplyIdentityId = replyIdentityDirty
    ? replyIdentityId
    : replyIdentityId || (sendIdentities.data ?? [])[0]?.id || ""
  const effectiveReplySubject = replySubjectDirty
    ? replySubject
    : defaultReplySubject(detail.data?.ticket.subject ?? null)

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
          <CardDescription>Use dev login from the mailboxes page, then retry this ticket URL.</CardDescription>
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

  const role = me.data.role

  if (detail.isLoading) {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center gap-2 text-sm text-neutral-700">
            <Spinner /> Loading ticket…
          </div>
        </CardContent>
      </Card>
    )
  }

  if (detail.isError) {
    if (detail.error instanceof ApiError && detail.error.status === 404) {
      return (
        <Card>
          <CardHeader>
            <CardTitle>Ticket not found</CardTitle>
            <CardDescription>This ticket does not exist in your active organization.</CardDescription>
          </CardHeader>
          <CardContent>
            <Link
              href="/tickets"
              className="inline-flex h-10 items-center justify-center rounded-lg bg-neutral-900 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-neutral-800 active:bg-neutral-950"
            >
              Back to Inbox
            </Link>
          </CardContent>
        </Card>
      )
    }
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">
            {detail.error instanceof ApiError ? detail.error.detail : "Failed to load ticket detail"}
          </div>
        </CardContent>
      </Card>
    )
  }

  const data = detail.data
  if (!data) return null

  const currentAssignee = data.ticket.assignee_queue_id
    ? `queue:${data.ticket.assignee_queue_id}`
    : data.ticket.assignee_user_id
      ? `user:${data.ticket.assignee_user_id}`
      : "unassigned"

  const handleUpdateSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const nextStatus = String(form.get("status") ?? "")
    const nextPriority = String(form.get("priority") ?? "")
    const nextQueue = String(form.get("assignee_queue_id") ?? "")
    if (!nextStatus || !nextPriority) {
      setControlError("Status and priority are required")
      return
    }
    if (assignmentMode === "queue" && !nextQueue) {
      setControlError("Select a queue when assignment mode is queue")
      return
    }
    updateTicket.mutate({
      status: nextStatus,
      priority: nextPriority,
      assignmentMode,
      queueId: nextQueue || undefined
    })
  }

  const handleCreateNote = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmed = noteBody.trim()
    if (!trimmed) {
      setNoteError("Note body cannot be empty")
      return
    }
    createNote.mutate(trimmed)
  }

  const handleQueueReply = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const toEmails = parseEmailCsv(replyTo)
    const ccEmails = parseEmailCsv(replyCc)
    const subject = effectiveReplySubject.trim()
    const bodyText = replyBody.trim()

    if (!selectedReplyIdentityId) {
      setReplyError("Select a send identity")
      return
    }
    if (toEmails.length === 0) {
      setReplyError("Enter at least one To recipient")
      return
    }
    if (!subject) {
      setReplyError("Subject is required")
      return
    }
    if (!bodyText) {
      setReplyError("Reply body cannot be empty")
      return
    }

    queueReply.mutate({
      sendIdentityId: selectedReplyIdentityId,
      toEmails,
      ccEmails,
      subject,
      bodyText,
    })
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={ticketStatusTone(data.ticket.status)}>{data.ticket.status.toUpperCase()}</Badge>
            <Badge tone="neutral">{data.ticket.ticket_code}</Badge>
          </div>
          <CardTitle className="mt-2">{data.ticket.subject || "(no subject)"}</CardTitle>
          <CardDescription>
            From {data.ticket.requester_email || "unknown"} · Last activity{" "}
            {formatDate(data.ticket.last_activity_at || data.ticket.updated_at)}
          </CardDescription>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Ticket Controls</CardTitle>
          <CardDescription>Update workflow state and assignment.</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="mb-3 text-sm text-neutral-600">Current assignee: {currentAssignee}</div>
          <form className="grid gap-3 md:grid-cols-2" onSubmit={handleUpdateSubmit}>
            <label className="grid gap-1 text-sm text-neutral-800">
              <span>Status</span>
              <select
                name="status"
                defaultValue={data.ticket.status}
                className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-800 outline-none ring-neutral-900/20 transition focus:ring-2"
              >
                <option value="new">new</option>
                <option value="open">open</option>
                <option value="pending">pending</option>
                <option value="resolved">resolved</option>
                <option value="closed">closed</option>
                <option value="spam">spam</option>
              </select>
            </label>
            <label className="grid gap-1 text-sm text-neutral-800">
              <span>Priority</span>
              <select
                name="priority"
                defaultValue={data.ticket.priority}
                className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-800 outline-none ring-neutral-900/20 transition focus:ring-2"
              >
                <option value="low">low</option>
                <option value="normal">normal</option>
                <option value="high">high</option>
                <option value="urgent">urgent</option>
              </select>
            </label>

            <label className="grid gap-1 text-sm text-neutral-800 md:col-span-2">
              <span>Assignment Mode</span>
              <select
                value={assignmentMode}
                onChange={(event) => setAssignmentMode(event.target.value as "keep" | "clear" | "queue")}
                className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-800 outline-none ring-neutral-900/20 transition focus:ring-2"
              >
                <option value="keep">Keep current assignee</option>
                <option value="clear">Clear assignee</option>
                <option value="queue">Assign to queue</option>
              </select>
            </label>

            {assignmentMode === "queue" ? (
              <label className="grid gap-1 text-sm text-neutral-800 md:col-span-2">
                <span>Queue</span>
                <select
                  name="assignee_queue_id"
                  defaultValue={data.ticket.assignee_queue_id ?? ""}
                  className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-800 outline-none ring-neutral-900/20 transition focus:ring-2"
                >
                  <option value="">Select queue…</option>
                  {(queues.data ?? []).map((queue) => (
                    <option key={queue.id} value={queue.id}>
                      {queue.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}

            {controlError ? <div className="text-sm text-red-700 md:col-span-2">{controlError}</div> : null}
            <div className="md:col-span-2">
              <Button type="submit" disabled={updateTicket.isPending || queues.isLoading}>
                {updateTicket.isPending ? (
                  <>
                    <Spinner /> Saving…
                  </>
                ) : (
                  "Save changes"
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {role !== "viewer" ? (
        <Card>
          <CardHeader>
            <CardTitle>Reply Composer</CardTitle>
            <CardDescription>
              Queue an outbound response from a verified send identity. Journal mirrors dedupe by `X-OSS-Message-ID`.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            {sendIdentities.isLoading ? (
              <div className="flex items-center gap-2 text-sm text-neutral-700">
                <Spinner /> Loading send identities…
              </div>
            ) : null}

            {!sendIdentities.isLoading && (sendIdentities.data ?? []).length === 0 ? (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
                No enabled send identities are available for this organization.
              </div>
            ) : null}

            <form className="grid gap-3" onSubmit={handleQueueReply}>
              <label className="grid gap-1 text-sm text-neutral-800">
                <span>From</span>
                <select
                  value={selectedReplyIdentityId}
                  onChange={(event) => {
                    setReplyIdentityDirty(true)
                    setReplyIdentityId(event.target.value)
                  }}
                  className="h-10 rounded-lg border border-neutral-200 bg-white px-3 text-sm text-neutral-800 outline-none ring-neutral-900/20 transition focus:ring-2"
                >
                  <option value="">Select send identity…</option>
                  {(sendIdentities.data ?? []).map((identity) => (
                    <option key={identity.id} value={identity.id}>
                      {identity.from_name ? `${identity.from_name} <${identity.from_email}>` : identity.from_email}
                    </option>
                  ))}
                </select>
                {preferredFrom && !selectedReplyIdentityId ? (
                  <div className="text-xs text-neutral-500">Suggested: {preferredFrom}</div>
                ) : null}
              </label>

              <label className="grid gap-1 text-sm text-neutral-800">
                <span>To (comma-separated)</span>
                <Input
                  value={replyTo}
                  onChange={(event) => setReplyTo(event.target.value)}
                  placeholder={data.ticket.requester_email || "customer@example.com"}
                />
              </label>

              <label className="grid gap-1 text-sm text-neutral-800">
                <span>Cc (optional, comma-separated)</span>
                <Input
                  value={replyCc}
                  onChange={(event) => setReplyCc(event.target.value)}
                  placeholder="billing@example.com, ops@example.com"
                />
              </label>

              <label className="grid gap-1 text-sm text-neutral-800">
                <span>Subject</span>
                <Input
                  value={effectiveReplySubject}
                  onChange={(event) => {
                    setReplySubjectDirty(true)
                    setReplySubject(event.target.value)
                  }}
                  placeholder={defaultReplySubject(data.ticket.subject)}
                />
              </label>

              <label className="grid gap-1 text-sm text-neutral-800">
                <span>Body</span>
                <textarea
                  value={replyBody}
                  onChange={(event) => setReplyBody(event.target.value)}
                  className="min-h-32 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-800 outline-none ring-neutral-900/20 transition focus:ring-2"
                  placeholder="Write your response"
                />
              </label>

              {replyError ? <div className="text-sm text-red-700">{replyError}</div> : null}
              {replyQueuedMessage ? <div className="text-sm text-green-700">{replyQueuedMessage}</div> : null}

              <div>
                <Button type="submit" disabled={queueReply.isPending || (sendIdentities.data ?? []).length === 0}>
                  {queueReply.isPending ? (
                    <>
                      <Spinner /> Queueing…
                    </>
                  ) : (
                    "Queue reply"
                  )}
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>Thread</CardTitle>
          <CardDescription>{data.messages.length} message(s)</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          {data.messages.length === 0 ? <div className="text-sm text-neutral-600">No thread messages yet.</div> : null}
          {data.messages.map((message) => (
            <div key={message.message_id} className="rounded-lg border border-neutral-200 bg-neutral-50 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="neutral">{message.direction}</Badge>
                <span className="text-xs text-neutral-500">stitched: {formatDate(message.stitched_at)}</span>
                {message.collision_group_id ? (
                  <span className="text-xs text-amber-700">collision group: {message.collision_group_id}</span>
                ) : null}
              </div>
              <div className="mt-2 text-sm font-medium text-neutral-900">{message.subject || "(no subject)"}</div>
              <div className="mt-1 text-xs text-neutral-600">
                From {message.from_email || "unknown"} · To {message.to_emails.join(", ") || "n/a"}
              </div>
              {message.body_html_sanitized ? (
                <div
                  className="prose prose-sm mt-3 max-w-none text-neutral-800"
                  dangerouslySetInnerHTML={{ __html: message.body_html_sanitized }}
                />
              ) : (
                <pre className="mt-3 whitespace-pre-wrap text-sm text-neutral-800">
                  {message.body_text || message.snippet || "(empty body)"}
                </pre>
              )}
              {message.attachments.length > 0 ? (
                <div className="mt-3">
                  <div className="text-xs font-medium uppercase tracking-wide text-neutral-500">Attachments</div>
                  <ul className="mt-1 list-disc pl-5 text-sm text-neutral-700">
                    {message.attachments.map((attachment) => (
                      <li key={attachment.id}>
                        <a
                          href={buildApiUrl(`/tickets/${ticketId}/attachments/${attachment.id}/download`)}
                          className="underline decoration-neutral-400 underline-offset-2 transition hover:text-neutral-900"
                        >
                          {attachment.filename || "(unnamed)"}
                        </a>{" "}
                        · {attachment.size_bytes} bytes
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {message.occurrences.length > 0 ? (
                <div className="mt-3">
                  <div className="text-xs font-medium uppercase tracking-wide text-neutral-500">
                    Routing Evidence
                  </div>
                  <div className="mt-2 grid gap-2">
                    {message.occurrences.map((occurrence) => (
                      <div
                        key={occurrence.id}
                        className="rounded-md border border-neutral-200 bg-white p-3 text-xs text-neutral-700"
                      >
                        <div>
                          recipient: {occurrence.original_recipient || "unknown"} · source: {" "}
                          {occurrence.original_recipient_source} · confidence:{" "}
                          {occurrence.original_recipient_confidence}
                        </div>
                        <div className="mt-1">
                          mailbox: {occurrence.mailbox_id} · gmail_message_id: {" "}
                          {occurrence.gmail_message_id}
                        </div>
                        {occurrence.route_error || occurrence.stitch_error || occurrence.parse_error ? (
                          <div className="mt-1 text-red-700">
                            errors: {" "}
                            {[occurrence.parse_error, occurrence.stitch_error, occurrence.route_error]
                              .filter(Boolean)
                              .join(" | ")}
                          </div>
                        ) : null}
                        <pre className="mt-2 overflow-x-auto text-[11px] text-neutral-600">
                          {JSON.stringify(occurrence.original_recipient_evidence, null, 2)}
                        </pre>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Events</CardTitle>
            <CardDescription>{data.events.length} event(s)</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            {data.events.length === 0 ? <div className="text-sm text-neutral-600">No events recorded.</div> : null}
            {data.events.map((event) => (
              <div key={event.id} className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
                <div className="text-sm font-medium text-neutral-900">{event.event_type}</div>
                <div className="text-xs text-neutral-600">{formatDate(event.created_at)}</div>
                <pre className="mt-2 overflow-x-auto text-xs text-neutral-700">
                  {JSON.stringify(event.event_data, null, 2)}
                </pre>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Internal Notes</CardTitle>
            <CardDescription>{data.notes.length} note(s)</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <form className="grid gap-2 rounded-lg border border-neutral-200 bg-white p-3" onSubmit={handleCreateNote}>
              <label className="text-sm font-medium text-neutral-900" htmlFor="note-body">
                Add internal note
              </label>
              <Input
                id="note-body"
                value={noteBody}
                onChange={(event) => setNoteBody(event.target.value)}
                placeholder="Write an internal note (not sent to customer)"
              />
              {noteError ? <div className="text-sm text-red-700">{noteError}</div> : null}
              <div>
                <Button type="submit" disabled={createNote.isPending}>
                  {createNote.isPending ? (
                    <>
                      <Spinner /> Posting…
                    </>
                  ) : (
                    "Add note"
                  )}
                </Button>
              </div>
            </form>
            {data.notes.length === 0 ? <div className="text-sm text-neutral-600">No internal notes yet.</div> : null}
            {data.notes.map((note) => (
              <div key={note.id} className="rounded-lg border border-neutral-200 bg-neutral-50 p-3">
                <div className="text-xs text-neutral-600">{formatDate(note.created_at)}</div>
                <pre className="mt-1 whitespace-pre-wrap text-sm text-neutral-800">{note.body_markdown}</pre>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
