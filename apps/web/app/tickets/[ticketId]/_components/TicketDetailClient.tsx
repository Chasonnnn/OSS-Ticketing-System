"use client"

import { useQuery } from "@tanstack/react-query"
import Link from "next/link"

import { Badge } from "../../../../components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../../../components/ui/card"
import { Spinner } from "../../../../components/ui/spinner"
import { ApiError, apiFetchJson } from "../../../../lib/api/client"
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

function formatDate(value: string | null): string {
  if (!value) return "n/a"
  const dt = new Date(value)
  if (Number.isNaN(dt.getTime())) return "n/a"
  return dt.toLocaleString()
}

export function TicketDetailClient({ ticketId }: { ticketId: string }) {
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
                        {attachment.filename || "(unnamed)"} · {attachment.size_bytes} bytes
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
                          recipient: {occurrence.original_recipient || "unknown"} · source:{" "}
                          {occurrence.original_recipient_source} · confidence:{" "}
                          {occurrence.original_recipient_confidence}
                        </div>
                        <div className="mt-1">
                          mailbox: {occurrence.mailbox_id} · gmail_message_id:{" "}
                          {occurrence.gmail_message_id}
                        </div>
                        {occurrence.route_error || occurrence.stitch_error || occurrence.parse_error ? (
                          <div className="mt-1 text-red-700">
                            errors:{" "}
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
