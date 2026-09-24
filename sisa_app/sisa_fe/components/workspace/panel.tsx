import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

export function Panel({
  className,
  children,
}: {
  className?: string
  children: ReactNode
}) {
  return (
    <section
      className={cn(
        "flex flex-col rounded-xl border border-line bg-white shadow-[0_1px_2px_rgba(15,27,42,0.04)]",
        className
      )}
    >
      {children}
    </section>
  )
}

export function PanelHeader({
  title,
  aside,
  className,
}: {
  title: ReactNode
  aside?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex min-h-11 items-center justify-between gap-3 border-b border-line px-4 py-2",
        className
      )}
    >
      <h2 className="m-0 text-[11px] font-semibold tracking-[0.12em] text-brand uppercase">
        {title}
      </h2>
      {aside}
    </div>
  )
}

export function DemoBadge() {
  return (
    <span
      title="Mock data: verification isn't connected yet"
      className="rounded-full border border-dashed border-brand-accent/50 px-1.5 font-mono text-[9px] leading-4 tracking-[0.08em] text-brand-accent uppercase"
    >
      Demo
    </span>
  )
}
