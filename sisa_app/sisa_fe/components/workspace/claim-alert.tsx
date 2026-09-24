"use client"

import { TriangleAlert, X } from "lucide-react"

import type { ClaimAlert } from "@/hooks/use-claim-alerts"

/** A short-lived card over the video; click it to open the claim. */
export function ClaimAlertOverlay({
  alert,
  onOpen,
  onDismiss,
}: {
  alert: ClaimAlert | null
  onOpen: (id: string) => void
  onDismiss: () => void
}) {
  if (!alert) return null
  return (
    <div
      key={alert.key}
      role="status"
      className="absolute top-2 left-2 z-10 flex max-w-[calc(100%-1rem)] animate-in items-start gap-2 rounded-lg border-l-[3px] bg-white/95 py-2 pr-1.5 pl-2.5 shadow-lg backdrop-blur fade-in slide-in-from-top-2 sm:top-3 sm:left-3 sm:max-w-[70%]"
      style={{ borderLeftColor: alert.color }}
    >
      <button
        type="button"
        onClick={() => {
          onOpen(alert.claim.id)
          onDismiss()
        }}
        className="flex min-w-0 flex-col items-start gap-0.5 text-left"
      >
        <span
          className="flex items-center gap-1.5 text-[12px] font-semibold"
          style={{ color: alert.color }}
        >
          <TriangleAlert className="h-3.5 w-3.5" />
          {alert.label}
        </span>
        <span className="line-clamp-2 text-[12px] leading-snug text-ink sm:text-[13px]">
          {alert.claim.text}
        </span>
      </button>
      <button
        type="button"
        aria-label="Dismiss alert"
        onClick={onDismiss}
        className="shrink-0 rounded-full p-0.5 text-ink-faint hover:bg-canvas hover:text-ink"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}
