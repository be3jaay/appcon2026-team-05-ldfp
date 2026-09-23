"use client"

import { CircleAlert, LoaderCircle } from "lucide-react"
import { useMemo, type ReactNode } from "react"

import { cn } from "@/lib/utils"
import type {
  Claim,
  ClaimType,
  SegmentClaimStatus,
} from "@/hooks/use-claim-detection"

// Tuned for text on a light background (AA contrast for the chip labels).
export const CLAIM_COLORS: Record<ClaimType, string> = {
  fact: "#B45309",
  legal: "#1D5FA8",
  opinion: "#5B6B7F",
  promise: "#207A4E",
  sarcasm: "#7C3AED",
  figurative: "#0E7490",
  vague: "#BE185D",
}

export const CLAIM_LABELS: Record<ClaimType, string> = {
  fact: "Fact",
  legal: "Legal",
  opinion: "Opinion",
  promise: "Promise",
  sarcasm: "Sarcasm",
  figurative: "Figurative",
  vague: "Vague",
}

const STATUS_TITLES: Partial<Record<SegmentClaimStatus, string>> = {
  queued: "Queued for claim detection…",
  checking: "Checking for claims…",
  error: "Claim detection failed for this line",
}

interface Range {
  start: number
  end: number
  claim: Claim
}

function escapeRegExp(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
}

/** Finds each claim's verbatim quote in the text (case- and spacing-insensitive). */
function locate(text: string, claims: Claim[]) {
  const ranges: Range[] = []
  const unplaced: Claim[] = []
  for (const claim of claims) {
    const words = claim.quote?.trim().split(/\s+/).filter(Boolean)
    const match = words?.length
      ? new RegExp(words.map(escapeRegExp).join("\\s+"), "i").exec(text)
      : null
    const range = match && {
      start: match.index,
      end: match.index + match[0].length,
      claim,
    }
    if (
      range &&
      !ranges.some((r) => range.start < r.end && r.start < range.end)
    ) {
      ranges.push(range)
    } else {
      unplaced.push(claim)
    }
  }
  ranges.sort((a, b) => a.start - b.start)
  return { ranges, unplaced }
}

function describe(claim: Claim) {
  const parts = [
    `${claim.type.toUpperCase()} · ${Math.round(claim.checkworthiness * 100)}% check-worthy`,
    claim.text,
    claim.reason,
  ]
  if (claim.literal_claim) parts.push(`Literal claim: ${claim.literal_claim}`)
  return parts.join("\n")
}

function ClaimMark({ claim, children }: { claim: Claim; children: ReactNode }) {
  const color = CLAIM_COLORS[claim.type]
  return (
    <mark
      title={describe(claim)}
      className="cursor-help rounded-[3px] px-[2px] text-inherit decoration-2 underline-offset-4"
      style={{
        backgroundColor: `${color}1f`,
        textDecorationLine: "underline",
        textDecorationColor: color,
      }}
    >
      {children}
    </mark>
  )
}

export function ClaimTypeChip({
  type,
  className,
  title,
}: {
  type: ClaimType
  className?: string
  title?: string
}) {
  const color = CLAIM_COLORS[type]
  return (
    <span
      title={title}
      className={cn(
        "inline-flex items-center rounded-full px-2 font-mono text-[10px] leading-[18px] font-medium tracking-[0.06em] uppercase",
        className
      )}
      style={{ backgroundColor: `${color}14`, color }}
    >
      {CLAIM_LABELS[type]}
    </span>
  )
}

function ClaimChip({ claim }: { claim: Claim }) {
  return (
    <ClaimTypeChip
      type={claim.type}
      title={describe(claim)}
      className="ml-1.5 cursor-help align-middle"
    />
  )
}

/**
 * Transcript text with detected claims highlighted by type, and a spinner
 * while the segment is still waiting for / going through claim detection.
 */
export function ClaimText({
  text,
  claims = [],
  status,
  className,
}: {
  text: string
  claims?: Claim[]
  status?: SegmentClaimStatus
  className?: string
}) {
  const { ranges, unplaced } = useMemo(
    () => locate(text, claims),
    [text, claims]
  )

  const pieces: ReactNode[] = []
  let cursor = 0
  for (const r of ranges) {
    if (r.start > cursor) pieces.push(text.slice(cursor, r.start))
    pieces.push(
      <ClaimMark key={r.claim.id} claim={r.claim}>
        {text.slice(r.start, r.end)}
      </ClaimMark>
    )
    cursor = r.end
  }
  if (cursor < text.length) pieces.push(text.slice(cursor))

  const pending = status === "queued" || status === "checking"

  return (
    <p className={cn("m-0", className)}>
      {pieces}
      {unplaced.map((claim) => (
        <ClaimChip key={claim.id} claim={claim} />
      ))}
      {pending ? (
        <LoaderCircle
          aria-label={STATUS_TITLES[status]}
          className={cn(
            "ml-1.5 inline-block h-[0.8em] w-[0.8em] animate-spin align-baseline",
            status === "queued" ? "text-ink-faint" : "text-brand-accent"
          )}
        >
          <title>{STATUS_TITLES[status]}</title>
        </LoaderCircle>
      ) : null}
      {status === "error" ? (
        <CircleAlert
          aria-label={STATUS_TITLES.error}
          className="ml-1.5 inline-block h-[0.8em] w-[0.8em] align-baseline text-[#C2410C]"
        >
          <title>{STATUS_TITLES.error}</title>
        </CircleAlert>
      ) : null}
    </p>
  )
}

export function ClaimLegend({ className }: { className?: string }) {
  return (
    <div
      className={cn("flex flex-wrap items-center gap-x-3 gap-y-1", className)}
    >
      {(Object.keys(CLAIM_COLORS) as ClaimType[]).map((type) => (
        <span key={type} className="flex items-center gap-1.5">
          <span
            className="h-[3px] w-3 rounded-full"
            style={{ backgroundColor: CLAIM_COLORS[type] }}
          />
          {CLAIM_LABELS[type]}
        </span>
      ))}
    </div>
  )
}
