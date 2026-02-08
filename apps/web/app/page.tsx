import Link from "next/link"

export default function HomePage() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-16">
      <h1 className="text-3xl font-semibold tracking-tight">OSS Ticketing System</h1>
      <p className="mt-4 text-base leading-7 text-neutral-700">
        This app ingests mail from a Google Workspace journal mailbox and stores tickets and messages in
        Postgres as the system of record.
      </p>
      <div className="mt-10 grid gap-4 rounded-xl border border-neutral-200 bg-white p-6 shadow-sm">
        <div>
          <div className="text-sm font-medium text-neutral-900">Next steps</div>
          <ul className="mt-2 list-disc pl-5 text-sm text-neutral-700">
            <li>Start Postgres and MinIO with Docker Compose.</li>
            <li>Run the API and confirm /healthz and /readyz.</li>
            <li>Connect a journal mailbox and run the ingestion worker.</li>
          </ul>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Link
            href="/mailboxes"
            className="inline-flex h-10 items-center justify-center rounded-lg bg-neutral-900 px-4 text-sm font-medium text-white shadow-sm transition hover:bg-neutral-800 active:bg-neutral-950"
          >
            Open Mailboxes
          </Link>
          <div className="text-sm text-neutral-600">
            Use dev login to create a session, then connect the journal mailbox via OAuth.
          </div>
        </div>
      </div>
    </main>
  )
}
