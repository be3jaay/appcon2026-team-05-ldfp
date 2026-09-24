"use client"

import { CircleAlert } from "lucide-react"
import { useMemo, type KeyboardEvent, type ReactNode } from "react"

import { cn } from "@/lib/utils"
import { checkingSources, VERDICT_META, type Verdict } from "@/lib/verification"
import { CheckingStatus } from "@/components/claims/checking-status"
import { VerdictIcon } from "@/components/claims/verdict-badge"
import {
  RhetoricMarker,
  rhetoricSummary,
} from "@/components/claims/rhetoric-badges"
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
  fact: "Fact claim",
  legal: "Legal claim",
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

const DETECTION_LABELS: Partial<Record<SegmentClaimStatus, string[]>> = {
  queued: ["Queued…"],
  checking: ["Reading the line…", "Looking for claims…"],
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

// Verdicts worth showing inline next to the words (the others are shown in panels).
const INLINE_VERDICTS = new Set<Verdict>([
  "factual",
  "misleading",
  "lacks-context",
  "no-evidence",
  "checking",
])

function describe(claim: Claim, verdict?: Verdict) {
  const parts = [
    ...(verdict
      ? [`${VERDICT_META[verdict].label}: ${VERDICT_META[verdict].description}`]
      : []),
    `${CLAIM_LABELS[claim.type]} · ${Math.round(claim.checkworthiness * 100)}% check-worthy`,
    claim.text,
    claim.reason,
  ]
  if (claim.literal_claim) parts.push(`Literal claim: ${claim.literal_claim}`)
  const rhetoric = rhetoricSummary(claim)
  if (rhetoric) parts.push(rhetoric)
  return parts.join("\n")
}

function clickProps(onSelect: (() => void) | undefined) {
  if (!onSelect) return {}
  return {
    role: "button",
    tabIndex: 0,
    onClick: onSelect,
    onKeyDown: (e: KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault()
        onSelect()
      }
    },
  }
}

function ClaimMark({
  claim,
  verdict,
  onSelect,
  children,
}: {
  claim: Claim
  verdict?: Verdict
  onSelect?: () => void
  children: ReactNode
}) {
  const color = CLAIM_COLORS[claim.type]
  return (
    <mark
      title={describe(claim, verdict)}
      {...clickProps(onSelect)}
      className={cn(
        "rounded-[3px] px-[2px] text-inherit decoration-2 underline-offset-4",
        onSelect
          ? "cursor-pointer transition-[filter] hover:brightness-95 focus-visible:outline-2 focus-visible:outline-brand-accent"
          : "cursor-help"
      )}
      style={{
        backgroundColor: `${color}1f`,
        textDecorationLine: "underline",
        textDecorationColor: color,
      }}
    >
      {children}
      {verdict && INLINE_VERDICTS.has(verdict) ? (
        <VerdictIcon
          verdict={verdict}
          className="ml-1 h-[0.85em] w-[0.85em] -translate-y-px align-middle"
        />
      ) : null}
      <RhetoricMarker claim={claim} />
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

function ClaimChip({
  claim,
  verdict,
  onSelect,
}: {
  claim: Claim
  verdict?: Verdict
  onSelect?: () => void
}) {
  return (
    <span {...clickProps(onSelect)}>
      <ClaimTypeChip
        type={claim.type}
        title={describe(claim, verdict)}
        className={cn(
          "ml-1.5 align-middle",
          onSelect ? "cursor-pointer" : "cursor-help"
        )}
      />
    </span>
  )
}

/** Sources still being consulted for this line, newest claim first. */
function sourcesInFlight(claims: Claim[], verdicts: Record<string, Verdict>) {
  const checking = claims.filter((c) => verdicts[c.id] === "checking")
  const labels = checking.flatMap(checkingSources).map((s) => `Checking ${s}…`)
  return [...new Set(labels)]
}

/**
 * Transcript text with detected claims highlighted by type. While a line is
 * still being processed it names what is happening - the detector reading the
 * line, then each source its claims are checked against.
 */
export function ClaimText({
  text,
  claims = [],
  status,
  verdicts = {},
  onSelectClaim,
  className,
}: {
  text: string
  claims?: Claim[]
  status?: SegmentClaimStatus
  /** Verification verdict per claim id. */
  verdicts?: Record<string, Verdict>
  /** Makes each highlight clickable (e.g. to open the claim in the claims panel). */
  onSelectClaim?: (id: string) => void
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
      <ClaimMark
        key={r.claim.id}
        claim={r.claim}
        verdict={verdicts[r.claim.id]}
        onSelect={onSelectClaim && (() => onSelectClaim(r.claim.id))}
      >
        {text.slice(r.start, r.end)}
      </ClaimMark>
    )
    cursor = r.end
  }
  if (cursor < text.length) pieces.push(text.slice(cursor))

  const inFlight = useMemo(
    () => sourcesInFlight(claims, verdicts),
    [claims, verdicts]
  )
  // Detection comes first; once claims exist, name the sources they go to.
  const activity = inFlight.length
    ? inFlight
    : status === "queued" || status === "checking"
      ? (DETECTION_LABELS[status] ?? [])
      : []

  return (
    <p className={cn("m-0", className)}>
      {pieces}
      {unplaced.map((claim) => (
        <ClaimChip
          key={claim.id}
          claim={claim}
          verdict={verdicts[claim.id]}
          onSelect={onSelectClaim && (() => onSelectClaim(claim.id))}
        />
      ))}
      {activity.length ? (
        <CheckingStatus
          labels={activity}
          muted={!inFlight.length && status === "queued"}
          title={inFlight.length || !status ? undefined : STATUS_TITLES[status]}
        />
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
