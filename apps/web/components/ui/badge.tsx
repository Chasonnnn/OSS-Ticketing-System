import { cn } from "../../lib/cn"

type Tone = "neutral" | "green" | "amber" | "red"

export function Badge({
  tone = "neutral",
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset",
        tone === "neutral" && "bg-neutral-50 text-neutral-700 ring-neutral-200",
        tone === "green" && "bg-emerald-50 text-emerald-800 ring-emerald-200",
        tone === "amber" && "bg-amber-50 text-amber-800 ring-amber-200",
        tone === "red" && "bg-red-50 text-red-800 ring-red-200",
        className
      )}
      {...props}
    />
  )
}

