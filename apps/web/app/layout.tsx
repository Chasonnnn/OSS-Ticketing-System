import "./globals.css"

import type { Metadata } from "next"
import Link from "next/link"

import { Providers } from "../components/providers"

export const metadata: Metadata = {
  title: "OSS Ticketing System",
  description: "Enterprise-grade ticketing system for Google Workspace journal ingestion"
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-neutral-50 text-neutral-900">
        <Providers>
          <div className="min-h-screen bg-[radial-gradient(1000px_circle_at_20%_0%,rgba(10,10,10,0.06),transparent_55%),radial-gradient(900px_circle_at_80%_10%,rgba(120,113,108,0.08),transparent_55%)]">
            <header className="sticky top-0 z-10 border-b border-neutral-200 bg-white/75 backdrop-blur">
              <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
                <Link href="/" className="text-sm font-semibold tracking-tight">
                  OSS Ticketing
                </Link>
                <nav className="flex items-center gap-4 text-sm text-neutral-700">
                  <Link href="/tickets" className="hover:text-neutral-900">
                    Tickets
                  </Link>
                  <Link href="/mailboxes" className="hover:text-neutral-900">
                    Mailboxes
                  </Link>
                </nav>
              </div>
            </header>
            {children}
          </div>
        </Providers>
      </body>
    </html>
  )
}
