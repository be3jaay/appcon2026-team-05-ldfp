import { GitCompareArrows, MessageSquareWarning } from "lucide-react"

import { cn } from "@/lib/utils"
import type { Claim } from "@/hooks/use-claim-detection"

export const FALLACY_LABELS: Record<string, string> = {
  ad_hominem: "Ad hominem",
  straw_man: "Straw man",
  whataboutism: "Whataboutism",
  red_herring: "Red herring",
  false_dilemma: "False dilemma",
  slippery_slope: "Slippery slope",
  hasty_generalization: "Hasty generalization",
  appeal_to_emotion: "Appeal to emotion",
  appeal_to_authority: "Appeal to authority",
  bandwagon: "Bandwagon",
}

const RHETORIC_COLOR = "#9A3412"
const CONFLICT_COLOR = "#6D28D9"

/** Evasion, a fallacy, or a conflict with an earlier claim. */
export function hasRhetoric(claim: Claim): boolean {
  return Boolean(claim.evasion || claim.fallacy || claim.contradicts)
}

export function rhetoricSummary(claim: Claim): string | null {
  if (!hasRhetoric(claim)) return null
  const parts = [
    claim.evasion ? "Evasive answer" : null,
    claim.fallacy
      ? `Fallacy: ${FALLACY_LABELS[claim.fallacy] ?? claim.fallacy}`
      : null,
  ].filter(Boolean)
  const lines = parts.length
    ? [
        parts.join(" · ") +
          (claim.rhetoric_note ? ` — ${claim.rhetoric_note}` : ""),
      ]
    : []
  if (claim.contradicts)
    lines.push(
      "Conflicts with an earlier claim" +
        (claim.contradiction_note ? ` — ${claim.contradiction_note}` : "")
    )
  return lines.join("\n")
}

/** "Evasive" / "Fallacy: …" / "Conflicts with earlier" chips; notes explain them on hover. */
export function RhetoricBadges({
  claim,
  onOpenClaim,
  className,
}: {
  claim: Claim
  /** Makes the conflict chip open the earlier claim. */
  onOpenClaim?: (id: string) => void
  className?: string
}) {
  if (!hasRhetoric(claim)) return null
  const chip =
    "inline-flex items-center gap-1 rounded-full px-2 text-[11px] leading-5 font-semibold"
  const style = {
    backgroundColor: `${RHETORIC_COLOR}12`,
    color: RHETORIC_COLOR,
  }
  return (
    <span className={cn("inline-flex flex-wrap gap-1.5", className)}>
      {claim.evasion ? (
        <span
          className={chip}
          style={style}
          title={claim.rhetoric_note ?? undefined}
        >
          <MessageSquareWarning className="h-3 w-3" />
          Evasive
        </span>
      ) : null}
      {claim.fallacy ? (
        <span
          className={chip}
          style={style}
          title={claim.rhetoric_note ?? undefined}
        >
          <MessageSquareWarning className="h-3 w-3" />
          {FALLACY_LABELS[claim.fallacy] ?? claim.fallacy}
        </span>
      ) : null}
      {claim.contradicts ? (
        <ConflictChip
          className={chip}
          note={claim.contradiction_note}
          onOpen={
            onOpenClaim && claim.contradicts
              ? () => onOpenClaim(claim.contradicts as string)
              : undefined
          }
        />
      ) : null}
    </span>
  )
}

function ConflictChip({
  className,
  note,
  onOpen,
}: {
  className: string
  note?: string | null
  onOpen?: () => void
}) {
  const style = {
    backgroundColor: `${CONFLICT_COLOR}12`,
    color: CONFLICT_COLOR,
  }
  const content = (
    <>
      <GitCompareArrows className="h-3 w-3" />
      Conflicts with earlier
    </>
  )
  if (!onOpen)
    return (
      <span className={className} style={style} title={note ?? undefined}>
        {content}
      </span>
    )
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation()
        onOpen()
      }}
      className={cn(className, "hover:underline")}
      style={style}
      title={note ? `${note} (click to open the earlier claim)` : undefined}
    >
      {content}
    </button>
  )
}

/** Small inline marker for the transcript. */
export function RhetoricMarker({ claim }: { claim: Claim }) {
  const summary = rhetoricSummary(claim)
  if (!summary) return null
  return (
    <MessageSquareWarning
      aria-label={summary}
      className="ml-1 inline-block h-[0.85em] w-[0.85em] -translate-y-px align-middle"
      style={{ color: RHETORIC_COLOR }}
    >
      <title>{summary}</title>
    </MessageSquareWarning>
  )
}
