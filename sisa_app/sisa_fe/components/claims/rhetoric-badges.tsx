import { MessageSquareWarning } from "lucide-react"

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

export function hasRhetoric(claim: Claim): boolean {
  return Boolean(claim.evasion || claim.fallacy)
}

export function rhetoricSummary(claim: Claim): string | null {
  if (!hasRhetoric(claim)) return null
  const parts = [
    claim.evasion ? "Evasive answer" : null,
    claim.fallacy
      ? `Fallacy: ${FALLACY_LABELS[claim.fallacy] ?? claim.fallacy}`
      : null,
  ].filter(Boolean)
  return (
    parts.join(" · ") + (claim.rhetoric_note ? ` — ${claim.rhetoric_note}` : "")
  )
}

/** "Evasive" / "Fallacy: …" chips; the note explains them on hover. */
export function RhetoricBadges({
  claim,
  className,
}: {
  claim: Claim
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
    </span>
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
