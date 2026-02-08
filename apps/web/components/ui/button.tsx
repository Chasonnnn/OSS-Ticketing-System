"use client"

import type { ButtonHTMLAttributes } from "react"

import { cn } from "../../lib/cn"

type Variant = "primary" | "secondary" | "danger" | "ghost"
type Size = "sm" | "md"

export function Button({
  className,
  variant = "primary",
  size = "md",
  disabled,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  size?: Size
}) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-neutral-900/20",
        "disabled:cursor-not-allowed disabled:opacity-60",
        size === "sm" ? "h-9 px-3 text-sm" : "h-10 px-4 text-sm",
        variant === "primary" &&
          "bg-neutral-900 text-white shadow-sm hover:bg-neutral-800 active:bg-neutral-950",
        variant === "secondary" &&
          "bg-white text-neutral-900 shadow-sm ring-1 ring-neutral-200 hover:bg-neutral-50 active:bg-neutral-100",
        variant === "danger" &&
          "bg-red-600 text-white shadow-sm hover:bg-red-500 active:bg-red-700",
        variant === "ghost" && "bg-transparent text-neutral-900 hover:bg-neutral-100 active:bg-neutral-200",
        className
      )}
      disabled={disabled}
      {...props}
    />
  )
}

