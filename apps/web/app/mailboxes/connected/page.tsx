import { ConnectedClient } from "./ConnectedClient"

export default async function Page({
  searchParams
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>
}) {
  const qs = await searchParams
  const mailboxId = typeof qs.mailbox_id === "string" ? qs.mailbox_id : null

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <ConnectedClient mailboxId={mailboxId} />
    </main>
  )
}

