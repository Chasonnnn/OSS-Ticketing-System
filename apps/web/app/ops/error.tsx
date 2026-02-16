"use client"

import { useEffect } from "react"

import { Button } from "../../components/ui/button"

export default function Error({
  error,
  reset
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    console.error(error)
  }, [error])

  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-red-800">
        <h1 className="text-base font-semibold text-red-900">Ops dashboard failed to load</h1>
        <p className="mt-2 text-sm">{error.message || "Unexpected error while rendering operations tools."}</p>
        <div className="mt-4">
          <Button type="button" variant="secondary" onClick={() => reset()}>
            Retry
          </Button>
        </div>
      </div>
    </main>
  )
}
