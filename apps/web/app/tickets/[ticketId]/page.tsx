import { TicketDetailClient } from "./_components/TicketDetailClient"

export default async function Page({ params }: { params: Promise<{ ticketId: string }> }) {
  const { ticketId } = await params
  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <TicketDetailClient ticketId={ticketId} />
    </main>
  )
}
