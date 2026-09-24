"use client"

import {
  ArrowUpRight,
  Ban,
  Check,
  ChevronDown,
  LoaderCircle,
  Radio,
  StickyNote,
  X,
} from "lucide-react"
import { useState } from "react"

import { cn } from "@/lib/utils"
import { formatTime } from "@/lib/video"
import {
  METHOD_NOTE,
  RELIABILITY_LABEL,
  STATEMENT_KIND,
  VERDICT_META,
  ratingVerdict,
  verdictOf,
  type EvidenceItem,
  type VerifyState,
} from "@/lib/verification"
import type { Claim } from "@/hooks/use-claim-detection"
import {
  REVIEW_ACTIONS,
  REVIEW_HINTS,
  type ClaimReview,
  type ReviewDecision,
} from "@/hooks/use-claim-review"
import { ClaimTypeChip, CLAIM_COLORS } from "@/components/claims/claim-text"
import { VerdictBadge } from "@/components/claims/verdict-badge"
import { RhetoricBadges } from "@/components/claims/rhetoric-badges"

export function claimTime(claim: Claim) {
  return claim.timestamp !== null ? formatTime(claim.timestamp / 1000) : null
}

function formatPesos(amount: number) {
  for (const [size, suffix] of [
    [1e9, "B"],
    [1e6, "M"],
  ] as const) {
    if (Math.abs(amount) >= size)
      return `₱${(amount / size).toLocaleString(undefined, { maximumFractionDigits: 2 })}${suffix}`
  }
  return `₱${amount.toLocaleString()}`
}

function formatValue(data: EvidenceItem["data"]) {
  if (data.value === null) return null
  let value: string
  if (data.unit === "pesos") value = formatPesos(data.value)
  else if (data.unit === "percent") value = `${data.value.toLocaleString()}%`
  else if (data.unit === "projects")
    value = `${data.value.toLocaleString()} project records`
  else
    value = `${data.value.toLocaleString()}${data.unit ? ` ${data.unit}` : ""}`
  // Flood control evidence repeats the scope in `geography`; the title already says it.
  const extra =
    data.unit === "pesos" || data.unit === "projects"
      ? []
      : [data.period, data.geography]
  return [value, ...extra].filter(Boolean).join(" · ")
}

function EvidenceCard({ item }: { item: EvidenceItem }) {
  const { source, data } = item
  const value = formatValue(data)
  return (
    <li className="rounded-lg border border-line bg-canvas/60 p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="m-0 text-[13px] leading-snug font-semibold text-ink">
            {source.title ?? source.name}
          </p>
          <p className="m-0 text-[11px] text-ink-faint">
            {source.name}
            {source.date ? ` · ${source.date}` : ""}
            {source.reliability ? (
              <span
                className={
                  source.reliability === "government" ||
                  source.reliability === "fact_checker" ||
                  source.reliability === "news"
                    ? "ml-1.5 rounded-full bg-brand-accent/10 px-1.5 text-[10px] font-semibold text-brand-accent"
                    : "ml-1.5 rounded-full bg-canvas px-1.5 text-[10px] font-semibold text-ink-faint"
                }
              >
                {RELIABILITY_LABEL[source.reliability] ?? source.reliability}
              </span>
            ) : null}
          </p>
        </div>
        <span className="flex shrink-0 items-center gap-1.5">
          <span
            className={cn(
              "rounded-full px-1.5 font-mono text-[9px] leading-4 tracking-[0.06em] uppercase",
              item.relevance === "DIRECT"
                ? "bg-brand-accent/10 text-brand-accent"
                : "bg-canvas text-ink-faint"
            )}
          >
            {item.relevance === "DIRECT"
              ? source.source_type === "PUBLISHED_FACT_CHECK"
                ? "Same claim"
                : "Exact match"
              : "Related"}
          </span>
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="text-brand-accent hover:text-brand"
            aria-label={`Open ${source.title ?? source.name}`}
          >
            <ArrowUpRight className="h-4 w-4" />
          </a>
        </span>
      </div>
      {value ? (
        <p className="m-0 mt-1.5 text-[15px] font-semibold text-ink">{value}</p>
      ) : null}
      {data.rating ? (
        <p className="m-0 mt-1.5 flex flex-wrap items-center gap-1.5 text-[12px] text-ink-muted">
          Rated
          <span
            className="rounded-full px-2 text-[12px] leading-5 font-semibold"
            style={{
              color:
                VERDICT_META[ratingVerdict(data.rating) ?? "no-evidence"].color,
              backgroundColor: `${VERDICT_META[ratingVerdict(data.rating) ?? "no-evidence"].color}14`,
            }}
          >
            {data.rating}
          </span>
          {data.claimant ? <span>· claim by {data.claimant}</span> : null}
        </p>
      ) : null}
      {data.relevant_text && source.source_type === "PUBLISHED_FACT_CHECK" ? (
        <p className="m-0 mt-1 text-[11px] font-semibold tracking-[0.06em] text-ink-faint uppercase">
          Reviewed claim
        </p>
      ) : null}
      {data.relevant_text ? (
        <blockquote className="m-0 mt-1.5 border-l-2 border-line pl-2 text-[12px] leading-relaxed text-ink-muted">
          {data.relevant_text}
        </blockquote>
      ) : null}
    </li>
  )
}

/** The claim sentence, its verdict and a one-line explanation; the rest
 * (evidence, quote, literal claim, rhetoric note, check-worthiness) folds away. */
export function ClaimDetail({
  claim,
  verifyState,
  earlier,
  onOpenClaim,
  review,
  onDecide,
  onNote,
}: {
  claim: Claim
  verifyState: VerifyState | undefined
  /** The earlier claim this one conflicts with, if any. */
  earlier?: Claim | null
  onOpenClaim?: (id: string) => void
  review?: ClaimReview
  onDecide?: (decision: ReviewDecision) => void
  onNote?: (note: string) => void
}) {
  const verdict = verdictOf(claim, verifyState)
  const meta = VERDICT_META[verdict]
  const result = verifyState?.state === "done" ? verifyState.result : null

  let explanation: string = meta.description
  if (result) explanation = result.assessment.explanation
  else if (verifyState?.state === "failed") explanation = verifyState.message
  else if (verdict === "not-checkable")
    explanation = STATEMENT_KIND[claim.type] ?? meta.description

  const methodNote = result ? METHOD_NOTE[result.assessment.method] : null
  const evidence = result?.evidence ?? []
  const worth = Math.round(claim.checkworthiness * 100)

  return (
    <div className="flex flex-col gap-2.5 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <VerdictBadge verdict={verdict} size="lg" />
        <ClaimTypeChip type={claim.type} />
        <RhetoricBadges claim={claim} onOpenClaim={onOpenClaim} />
        <span className="ml-auto font-mono text-[11px] text-ink-faint">
          Speaker {claim.speaker}
          {claimTime(claim) ? ` · ${claimTime(claim)}` : ""}
        </span>
      </div>

      <p className="m-0 text-[16px] leading-snug font-semibold text-ink lg:text-[17px]">
        {claim.text}
      </p>
      <p className="m-0 text-[13px] leading-relaxed text-ink-muted">
        {explanation}
      </p>

      {claim.contradicts ? (
        <ConflictNote claim={claim} earlier={earlier} onOpen={onOpenClaim} />
      ) : null}

      {onDecide && onNote ? (
        <ReviewBar
          key={`review-${claim.id}`}
          review={review}
          onDecide={onDecide}
          onNote={onNote}
        />
      ) : null}

      <details
        key={`details-${claim.id}`}
        className="group border-t border-line pt-2.5"
      >
        <summary className="flex cursor-pointer list-none items-center justify-between text-[12px] font-semibold text-brand-accent">
          {evidence.length ? `Evidence (${evidence.length})` : "Details"}
          <ChevronDown className="h-4 w-4 text-ink-faint transition-transform group-open:rotate-180" />
        </summary>
        <div className="flex flex-col gap-2.5 pt-2.5">
          {claim.rhetoric_note ? (
            <p className="m-0 rounded-lg bg-[#9A3412]/[0.05] px-2.5 py-2 text-[12px] leading-relaxed text-ink-muted">
              {claim.rhetoric_note}
            </p>
          ) : null}
          {claim.quote ? (
            <blockquote
              className="m-0 border-l-[3px] pl-3 text-[13px] leading-relaxed text-ink-muted italic"
              style={{ borderColor: CLAIM_COLORS[claim.type] }}
            >
              “{claim.quote}”
            </blockquote>
          ) : null}
          {claim.literal_claim ? (
            <p className="m-0 rounded-lg bg-canvas px-2.5 py-2 text-[12px] leading-relaxed text-ink-muted">
              <b className="text-ink">Literal claim:</b> {claim.literal_claim}
            </p>
          ) : null}
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-ink-faint">Check-worthiness</span>
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-canvas">
              <span
                className="block h-full rounded-full bg-brand-accent"
                style={{ width: `${worth}%` }}
              />
            </span>
            <span className="font-mono text-[11px] text-ink-muted">
              {worth}%
            </span>
          </div>
          {methodNote ? (
            <p className="m-0 text-[11px] text-ink-faint italic">
              {methodNote}
            </p>
          ) : null}
          {evidence.length ? (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {evidence.map((item) => (
                <EvidenceCard key={item.source.url} item={item} />
              ))}
            </ul>
          ) : null}
        </div>
      </details>
    </div>
  )
}

function ConflictNote({
  claim,
  earlier,
  onOpen,
}: {
  claim: Claim
  earlier?: Claim | null
  onOpen?: (id: string) => void
}) {
  return (
    <div className="flex flex-col gap-1 rounded-lg bg-[#6D28D9]/[0.05] px-2.5 py-2 text-[12px] leading-relaxed">
      {claim.contradiction_note ? (
        <p className="m-0 text-ink-muted">{claim.contradiction_note}</p>
      ) : null}
      {earlier ? (
        <button
          type="button"
          onClick={() => onOpen?.(earlier.id)}
          className="text-left text-[#6D28D9] hover:underline"
        >
          Earlier ({earlier.speaker ? `Speaker ${earlier.speaker}` : ""}
          {claimTime(earlier) ? ` · ${claimTime(earlier)}` : ""}): “
          {earlier.text}”
        </button>
      ) : null}
    </div>
  )
}

const DECISIONS: { id: ReviewDecision; icon: typeof Check; active: string }[] =
  [
    {
      id: "confirmed",
      icon: Check,
      active: "border-[#15803D] bg-[#15803D]/10 text-[#15803D]",
    },
    {
      id: "disputed",
      icon: X,
      active: "border-[#B91C1C] bg-[#B91C1C]/10 text-[#B91C1C]",
    },
    {
      id: "dismissed",
      icon: Ban,
      active: "border-ink-muted bg-canvas text-ink",
    },
  ]

/** The reviewer's call on SISA's result, plus a private note. */
function ReviewBar({
  review,
  onDecide,
  onNote,
}: {
  review?: ClaimReview
  onDecide: (decision: ReviewDecision) => void
  onNote: (note: string) => void
}) {
  const [noteOpen, setNoteOpen] = useState(Boolean(review?.note))
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-0.5 text-[11px] text-ink-faint">Your review</span>
        {DECISIONS.map(({ id, icon: Icon, active }) => (
          <button
            key={id}
            type="button"
            aria-pressed={review?.decision === id}
            title={REVIEW_HINTS[id]}
            onClick={() => onDecide(id)}
            className={cn(
              "flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors",
              review?.decision === id
                ? active
                : "border-line text-ink-muted hover:border-brand-accent/50 hover:text-ink"
            )}
          >
            <Icon className="h-3 w-3" />
            {REVIEW_ACTIONS[id]}
          </button>
        ))}
        <button
          type="button"
          aria-expanded={noteOpen}
          onClick={() => setNoteOpen((o) => !o)}
          className={cn(
            "flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors",
            review?.note
              ? "border-brand-accent/50 text-brand-accent"
              : "border-line text-ink-muted hover:text-ink"
          )}
        >
          <StickyNote className="h-3 w-3" />
          Note
        </button>
      </div>
      {noteOpen ? (
        <textarea
          value={review?.note ?? ""}
          onChange={(e) => onNote(e.target.value)}
          placeholder="Your note on this claim (included in the export)"
          rows={2}
          className="w-full resize-y rounded-lg border border-line bg-white px-2.5 py-1.5 text-[13px] text-ink placeholder:text-ink-faint focus:border-brand-accent focus:outline-none"
        />
      ) : null}
    </div>
  )
}

/** "Following live" / "Detecting in N lines", or a way back to live after picking a claim. */
export function LiveStatus({
  following,
  pendingCount,
  onFollowLive,
}: {
  following: boolean
  pendingCount: number
  onFollowLive: () => void
}) {
  if (!following) {
    return (
      <button
        type="button"
        onClick={onFollowLive}
        className="text-[11px] font-semibold whitespace-nowrap text-brand-accent hover:underline"
      >
        Back to live
      </button>
    )
  }
  return (
    <span className="flex items-center gap-1.5 text-[11px] whitespace-nowrap text-ink-muted">
      {pendingCount > 0 ? (
        <>
          <LoaderCircle className="h-3.5 w-3.5 animate-spin text-brand-accent" />
          <span className="hidden sm:inline">Detecting in</span> {pendingCount}{" "}
          {pendingCount === 1 ? "line" : "lines"}
        </>
      ) : (
        <>
          <Radio className="h-3.5 w-3.5 text-brand-accent" />
          Live
        </>
      )}
    </span>
  )
}
