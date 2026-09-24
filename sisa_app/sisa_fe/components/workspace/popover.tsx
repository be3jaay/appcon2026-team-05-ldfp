"use client"

import { Popover } from "@base-ui/react/popover"
import type { ReactNode } from "react"

import { cn } from "@/lib/utils"

/** A small click-to-open panel for secondary info (legend, sources, help). */
export function InfoPopover({
  trigger,
  label,
  title,
  align = "end",
  triggerClassName,
  className,
  children,
}: {
  trigger: ReactNode
  /** Accessible name for the trigger button. */
  label: string
  title?: ReactNode
  align?: "start" | "center" | "end"
  triggerClassName?: string
  className?: string
  children: ReactNode
}) {
  return (
    <Popover.Root>
      <Popover.Trigger aria-label={label} className={triggerClassName}>
        {trigger}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner sideOffset={8} align={align} className="z-50">
          <Popover.Popup
            className={cn(
              "w-[320px] max-w-[calc(100vw-2rem)] origin-[var(--transform-origin)] rounded-xl border border-line bg-white text-ink shadow-xl transition-[transform,opacity] duration-150 data-[ending-style]:scale-95 data-[ending-style]:opacity-0 data-[starting-style]:scale-95 data-[starting-style]:opacity-0",
              className
            )}
          >
            {title ? (
              <Popover.Title className="m-0 border-b border-line px-4 py-2.5 text-[11px] font-semibold tracking-[0.12em] text-brand uppercase">
                {title}
              </Popover.Title>
            ) : null}
            {children}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  )
}
