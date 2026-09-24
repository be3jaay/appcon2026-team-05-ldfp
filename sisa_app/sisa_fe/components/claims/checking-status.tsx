"use client"

import { useEffect, useState } from "react"

import { cn } from "@/lib/utils"

const ROTATE_MS = 1600

/** Cycles through `labels` while a check is running; stops at one label. */
export function useRotatingLabel(labels: string[], intervalMs = ROTATE_MS) {
  const [index, setIndex] = useState(0)
  const key = labels.join("|")

  useEffect(() => {
    setIndex(0)
    if (labels.length < 2) return
    const id = setInterval(
      () => setIndex((i) => (i + 1) % labels.length),
      intervalMs
    )
    return () => clearInterval(id)
    // The labels themselves, not their identity, decide the rotation.
  }, [key, labels.length, intervalMs])

  return labels[index % Math.max(labels.length, 1)] ?? null
}

/** Three bars bouncing like an equalizer, so a running check reads as activity. */
function ActivityBars({ muted }: { muted: boolean }) {
  return (
    <span aria-hidden className="flex items-end gap-[2px]">
      {[0, 120, 240].map((delay, i) => (
        <span
          key={delay}
          className={cn(
            "w-[2px] animate-pulse rounded-full",
            muted ? "bg-ink-faint" : "bg-brand-accent"
          )}
          style={{
            height: `${5 + i * 2}px`,
            animationDelay: `${delay}ms`,
            animationDuration: "900ms",
          }}
        />
      ))}
    </span>
  )
}

/**
 * Inline "what is happening right now" chip: names the source being checked
 * instead of showing an anonymous spinner.
 */
export function CheckingStatus({
  labels,
  muted = false,
  title,
  className,
}: {
  /** Rotated one by one, e.g. the sources this claim goes to. */
  labels: string[]
  muted?: boolean
  title?: string
  className?: string
}) {
  const label = useRotatingLabel(labels)
  if (!label) return null

  return (
    <span
      title={title ?? label}
      className={cn(
        "ml-1.5 inline-flex max-w-full items-center gap-1.5 rounded-full border px-2 py-[1px] align-middle font-mono text-[10px] leading-4 tracking-[0.04em] whitespace-nowrap",
        muted
          ? "border-line bg-canvas text-ink-faint"
          : "border-brand-accent/30 bg-brand-accent/[0.07] text-brand-accent",
        className
      )}
    >
      <ActivityBars muted={muted} />
      {/* Remounting on each label change replays the fade-in. */}
      <span key={label} className="animate-in truncate duration-300 fade-in">
        {label}
      </span>
    </span>
  )
}
