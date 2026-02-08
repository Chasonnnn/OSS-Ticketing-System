import "./globals.css"

import type { Metadata } from "next"

export const metadata: Metadata = {
  title: "OSS Ticketing System",
  description: "Enterprise-grade ticketing system for Google Workspace journal ingestion"
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-neutral-50 text-neutral-900">{children}</body>
    </html>
  )
}

