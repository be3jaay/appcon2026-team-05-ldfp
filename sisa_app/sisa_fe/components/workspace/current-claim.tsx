"use client"

import { ArrowUpRight, LoaderCircle, Radio } from "lucide-react"
import { useMemo } from "react"

import { cn } from "@/lib/utils"
import { formatTime } from "@/lib/video"
import { mockVerify, type Verification } from "@/lib/mock-verification"
import type { Claim } from "@/hooks/use-claim-detection"
import { ClaimTypeChip, CLAIM_COLORS } from "@/components/claims/claim-text"
import { DemoBadge, Panel, PanelHeader } from "@/components/workspace/panel"

export function claimTime(claim: Claim) {
  return claim.timestamp !== null ? formatTime(claim.timestamp / 1000) : null
}

function VerdictPill({ verification }: { verification: Verification }) {
  const pending = verification.verdict === "pending"
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-semibold",
        pending ? "bg-brand/[0.08] text-brand" : "bg-canvas text-ink-muted"
      )}
    >
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          pending ? "bg-brand-sky" : "bg-ink-faint"
        )}
      />
      {pending ? "Awaiting verification" : "Not checkable"}
    </span>
  )
}

function Evidence({ verification }: { verification: Verification }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center justify-between gap-2">
        <h3 className="m-0 text-[11px] font-semibold tracking-[0.12em] text-brand uppercase">
          Evidence found
        </h3>
        <DemoBadge />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <VerdictPill verification={verification} />
      </div>
      <p className="m-0 text-[12px] leading-relaxed text-ink-muted">
        {verification.summary}
      </p>
      {verification.evidence.length ? (
        <ul className="m-0 flex list-none flex-col gap-2 p-0">
          {verification.evidence.map((item) => (
            <li
              key={item.source.id}
              className="rounded-lg border border-line bg-canvas/60 p-2.5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="m-0 text-[13px] font-semibold text-ink">
                    {item.source.name}
                  </p>
                  <p className="m-0 text-[11px] text-ink-faint">
                    {item.source.publisher}
                  </p>
                </div>
                <a
                  href={item.source.url}
                  target="_blank"
                  rel="noreferrer"
                  className="shrink-0 text-brand-accent hover:text-brand"
                  aria-label={`Open ${item.source.name}`}
                >
                  <ArrowUpRight className="h-4 w-4" />
                </a>
              </div>
              <p className="m-0 mt-1.5 font-mono text-[11px] leading-snug break-words text-ink-muted">
                Query: “{item.query}”
              </p>
              <p className="m-0 mt-1 text-[12px] text-ink-muted italic">
                {item.note}
              </p>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

export function CurrentClaim({
  claim,
  following,
  pendingCount,
  onFollowLive,
  compact = false,
  className,
}: {
  claim: Claim | null
  following: boolean
  pendingCount: number
  onFollowLive: () => void
  compact?: boolean
  className?: string
}) {
  const verification = useMemo(
    () => (claim ? mockVerify(claim) : null),
    [claim]
  )

  const aside = following ? (
    <span className="flex items-center gap-1.5 text-[11px] text-ink-muted">
      {pendingCount > 0 ? (
        <>
          <LoaderCircle className="h-3.5 w-3.5 animate-spin text-brand-accent" />
          Checking {pendingCount} {pendingCount === 1 ? "line" : "lines"}
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

  return (
    <Panel className={className}>
      <PanelHeader title="Current claim" aside={aside} />
      {!claim || !verification ? (
        <p className="m-0 px-4 py-6 text-center text-[13px] leading-relaxed text-ink-faint">
          No claims detected yet.
          <br />
          They&apos;ll appear here as people speak.
        </p>
      ) : (
        <div className="flex flex-col gap-3 p-4">
          <div className="flex flex-wrap items-center gap-2">
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

          <div className="flex items-center gap-2">
            <span className="text-[11px] text-ink-faint">Check-worthiness</span>
            <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-canvas">
              <span
                className="block h-full rounded-full bg-brand-accent"
                style={{ width: `${Math.round(claim.checkworthiness * 100)}%` }}
              />
            </span>
            <span className="font-mono text-[11px] text-ink-muted">
              {Math.round(claim.checkworthiness * 100)}%
            </span>
          </div>

          {!compact ? (
            <p className="m-0 text-[12px] leading-relaxed text-ink-muted">
              {claim.reason}
            </p>
          ) : null}
          {claim.literal_claim ? (
            <p className="m-0 rounded-lg bg-canvas px-2.5 py-2 text-[12px] leading-relaxed text-ink-muted">
              <b className="text-ink">Literal claim:</b> {claim.literal_claim}
            </p>
          ) : null}

          {compact ? (
            <details className="group border-t border-line pt-2.5">
              <summary className="flex cursor-pointer list-none items-center justify-between text-[12px] font-semibold text-brand-accent">
                Evidence ({verification.evidence.length})
                <span className="text-ink-faint group-open:rotate-180">⌄</span>
              </summary>
              <div className="pt-2.5">
                <Evidence verification={verification} />
              </div>
            </details>
          ) : (
            <div className="border-t border-line pt-3">
              <Evidence verification={verification} />
            </div>
          )}
        </div>
      )}
    </Panel>
  )
}
