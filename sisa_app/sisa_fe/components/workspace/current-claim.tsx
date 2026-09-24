"use client"

import { ArrowUpRight, LoaderCircle, Radio } from "lucide-react"

import { cn } from "@/lib/utils"
import { formatTime } from "@/lib/video"
import {
  METHOD_NOTE,
  STATEMENT_KIND,
  VERDICT_META,
  ratingVerdict,
  verdictOf,
  type EvidenceItem,
  type VerifyState,
} from "@/lib/verification"
import type { Claim } from "@/hooks/use-claim-detection"
import { ClaimTypeChip, CLAIM_COLORS } from "@/components/claims/claim-text"
import { VerdictBadge } from "@/components/claims/verdict-badge"
import { Panel, PanelHeader } from "@/components/workspace/panel"

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

function Evidence({
  claim,
  state,
}: {
  claim: Claim
  state: VerifyState | undefined
}) {
  const verdict = verdictOf(claim, state)
  const meta = VERDICT_META[verdict]
  const result = state?.state === "done" ? state.result : null

  let explanation: string = meta.description
  if (result) explanation = result.assessment.explanation
  else if (state?.state === "failed") explanation = state.message
  else if (verdict === "not-checkable")
    explanation = STATEMENT_KIND[claim.type] ?? meta.description

  const methodNote = result ? METHOD_NOTE[result.assessment.method] : null

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="m-0 text-[11px] font-semibold tracking-[0.12em] text-brand uppercase">
          {verdict === "not-checkable" ? "Statement" : "Verification"}
        </h3>
        <VerdictBadge verdict={verdict} />
      </div>
      <p className="m-0 text-[13px] leading-relaxed text-ink">{explanation}</p>
      {methodNote ? (
        <p className="m-0 text-[11px] text-ink-faint italic">{methodNote}</p>
      ) : null}
      {result?.evidence.length ? (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {result.evidence.map((item) => (
            <EvidenceCard key={item.source.url} item={item} />
          ))}
        </ul>
      ) : null}
    </div>
  )
}

export function CurrentClaim({
  claim,
  verifyState,
  following,
  pendingCount,
  onFollowLive,
  compact = false,
  className,
}: {
  claim: Claim | null
  verifyState: VerifyState | undefined
  following: boolean
  pendingCount: number
  onFollowLive: () => void
  compact?: boolean
  className?: string
}) {
  const aside = following ? (
    <span className="flex items-center gap-1.5 text-[11px] text-ink-muted">
      {pendingCount > 0 ? (
        <>
          <LoaderCircle className="h-3.5 w-3.5 animate-spin text-brand-accent" />
          Detecting in {pendingCount} {pendingCount === 1 ? "line" : "lines"}
        </>
      ) : (
        <>
          <Radio className="h-3.5 w-3.5 text-brand-accent" />
          Following live
        </>
      )}
    </span>
  ) : (
    <button
      type="button"
      onClick={onFollowLive}
      className="text-[11px] font-semibold text-brand-accent hover:underline"
    >
      Back to live
    </button>
  )

  const verdict = claim ? verdictOf(claim, verifyState) : null

  return (
    <Panel className={className}>
      <PanelHeader title="Current claim" aside={aside} />
      {!claim || !verdict ? (
        <p className="m-0 px-4 py-6 text-center text-[13px] leading-relaxed text-ink-faint">
          No claims detected yet.
          <br />
          They&apos;ll appear here as people speak.
        </p>
      ) : (
        <div className="flex flex-col gap-3 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <VerdictBadge verdict={verdict} size="lg" />
            <ClaimTypeChip type={claim.type} />
            <span className="font-mono text-[11px] text-ink-faint">
              Speaker {claim.speaker}
              {claimTime(claim) ? ` · ${claimTime(claim)}` : ""}
            </span>
          </div>

          {claim.quote ? (
            <blockquote
              className="m-0 border-l-[3px] pl-3 text-[14px] leading-relaxed text-ink-muted italic"
              style={{ borderColor: CLAIM_COLORS[claim.type] }}
            >
              “{claim.quote}”
            </blockquote>
          ) : null}

          <p
            className={cn(
              "m-0 font-semibold text-ink",
              compact ? "text-[15px] leading-snug" : "text-[17px] leading-snug"
            )}
          >
            {claim.text}
          </p>

          {claim.literal_claim ? (
            <p className="m-0 rounded-lg bg-canvas px-2.5 py-2 text-[12px] leading-relaxed text-ink-muted">
              <b className="text-ink">Literal claim:</b> {claim.literal_claim}
            </p>
          ) : null}

          {!compact ? (
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-ink-faint">
                Check-worthiness
              </span>
              <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-canvas">
                <span
                  className="block h-full rounded-full bg-brand-accent"
                  style={{
                    width: `${Math.round(claim.checkworthiness * 100)}%`,
                  }}
                />
              </span>
              <span className="font-mono text-[11px] text-ink-muted">
                {Math.round(claim.checkworthiness * 100)}%
              </span>
            </div>
          ) : null}

          {compact ? (
            <details className="group border-t border-line pt-2.5">
              <summary className="flex cursor-pointer list-none items-center justify-between text-[12px] font-semibold text-brand-accent">
                {verifyState?.state === "done"
                  ? `Evidence (${verifyState.result.evidence.length})`
                  : "Details"}
                <span className="text-ink-faint group-open:rotate-180">⌄</span>
              </summary>
              <div className="pt-2.5">
                <Evidence claim={claim} state={verifyState} />
              </div>
            </details>
          ) : (
            <div className="border-t border-line pt-3">
              <Evidence claim={claim} state={verifyState} />
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}
