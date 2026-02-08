export default function Loading() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <div className="h-6 w-48 animate-pulse rounded bg-neutral-200" />
      <div className="mt-6 grid gap-4">
        <div className="h-40 animate-pulse rounded-xl border border-neutral-200 bg-white" />
        <div className="h-40 animate-pulse rounded-xl border border-neutral-200 bg-white" />
      </div>
    </main>
  )
}

