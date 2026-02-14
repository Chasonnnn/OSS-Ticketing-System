export default function Loading() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <div className="h-6 w-40 animate-pulse rounded bg-neutral-200" />
      <div className="mt-6 h-16 animate-pulse rounded-xl border border-neutral-200 bg-white" />
      <div className="mt-4 grid gap-3">
        <div className="h-32 animate-pulse rounded-xl border border-neutral-200 bg-white" />
        <div className="h-32 animate-pulse rounded-xl border border-neutral-200 bg-white" />
        <div className="h-32 animate-pulse rounded-xl border border-neutral-200 bg-white" />
      </div>
    </main>
  )
}
