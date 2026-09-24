"use client"

import { Download, FileJson, FileText } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  STATEMENT_KIND,
  isFactCheck,
  verdictOf,
  type VerifyState,
} from "@/lib/verification"
import type { Claim } from "@/hooks/use-claim-detection"
import type { useClaimFeed } from "@/hooks/use-claim-feed"
import { REVIEW_LABELS, type ClaimReviews } from "@/hooks/use-claim-review"
import { ClaimTypeChip } from "@/components/claims/claim-text"
import { VerdictBadge } from "@/components/claims/verdict-badge"
import { RhetoricBadges } from "@/components/claims/rhetoric-badges"
import {
  ClaimDetail,
  LiveStatus,
  claimTime,
} from "@/components/workspace/current-claim"
import { Panel } from "@/components/workspace/panel"
import { InfoPopover } from "@/components/workspace/popover"

export type ClaimsTab = "now" | "checked" | "other"

type Feed = ReturnType<typeof useClaimFeed>

const EMPTY: Record<ClaimsTab, string> = {
  now: "No claims detected yet. They'll appear here as people speak.",
  checked:
    "Earlier claims SISA looked up in its sources (and published fact-checks) will be listed here.",
  other:
    "Opinions, promises, sarcasm, figures of speech and vague statements go here.",
}

function ClaimList({
  claims,
  verifications,
  reviews,
  showVerdict,
  onSelect,
}: {
  claims: Claim[]
  verifications: Record<string, VerifyState>
  reviews: ClaimReviews["reviews"]
  showVerdict: boolean
  onSelect: (id: string) => void
}) {
  return (
    <ul className="m-0 flex list-none flex-col p-0">
      {claims.map((claim) => (
        <li key={claim.id} className="border-b border-line last:border-b-0">
          <button
            type="button"
            onClick={() => onSelect(claim.id)}
            className={cn(
              "flex w-full flex-col gap-1 px-4 py-2.5 text-left transition-colors hover:bg-canvas",
              reviews[claim.id]?.decision === "dismissed" && "opacity-50"
            )}
          >
            <span className="flex flex-wrap items-center gap-2">
              {showVerdict ? (
                <VerdictBadge
                  verdict={verdictOf(claim, verifications[claim.id])}
                />
              ) : (
                <ClaimTypeChip type={claim.type} />
              )}
              <RhetoricBadges claim={claim} />
              {reviews[claim.id]?.decision ? (
                <span className="text-[10px] font-semibold tracking-[0.06em] text-ink-muted uppercase">
                  {REVIEW_LABELS[reviews[claim.id].decision!]}
                </span>
              ) : null}
              <span className="ml-auto font-mono text-[10px] text-ink-faint">
                {claimTime(claim) ?? `Speaker ${claim.speaker}`}
              </span>
            </span>
            <span className="line-clamp-2 text-[13px] leading-snug text-ink">
              {claim.text}
            </span>
            {!showVerdict && STATEMENT_KIND[claim.type] ? (
              <span className="text-[11px] leading-snug text-ink-faint">
                {STATEMENT_KIND[claim.type]}
              </span>
            ) : null}
          </button>
        </li>
      ))}
    </ul>
  )
}

/** Download the session as a report for people or as data. */
function ExportMenu({
  disabled,
  onExport,
}: {
  disabled: boolean
  onExport: (format: "md" | "json") => void
}) {
  if (disabled) return null
  const item =
    "flex w-full items-start gap-2.5 px-4 py-2.5 text-left transition-colors hover:bg-canvas"
  return (
    <InfoPopover
      label="Export this session"
      title="Export this session"
      className="w-[280px]"
      triggerClassName="rounded-md p-1.5 text-ink-faint transition-colors hover:bg-canvas hover:text-brand-accent"
      trigger={<Download className="h-4 w-4" />}
    >
      <button type="button" className={item} onClick={() => onExport("md")}>
        <FileText className="mt-0.5 h-4 w-4 shrink-0 text-brand-accent" />
        <span className="flex flex-col">
          <span className="text-[13px] font-semibold text-ink">
            Report (.md)
          </span>
          <span className="text-[11px] text-ink-faint">
            Claims, verdicts, evidence links, your reviews and notes, and the
            transcript
          </span>
        </span>
      </button>
      <button type="button" className={item} onClick={() => onExport("json")}>
        <FileJson className="mt-0.5 h-4 w-4 shrink-0 text-brand-accent" />
        <span className="flex flex-col">
          <span className="text-[13px] font-semibold text-ink">
            Data (.json)
          </span>
          <span className="text-[11px] text-ink-faint">
            Everything, for other tools
          </span>
        </span>
      </button>
    </InfoPopover>
  )
}

/**
 * One panel for everything about claims: the claim in focus ("Now"), earlier
 * checked claims, and other statements (opinion, promise, sarcasm, ...).
 */
export function ClaimsPanel({
  feed,
  claims,
  verifications,
  review,
  tab,
  onTabChange,
  onExport,
  className,
}: {
  feed: Feed
  /** Every claim this session (to resolve "conflicts with" links). */
  claims: Claim[]
  verifications: Record<string, VerifyState>
  review: ClaimReviews
  tab: ClaimsTab
  onTabChange: (tab: ClaimsTab) => void
  onExport: (format: "md" | "json") => void
  className?: string
}) {
  const checked = feed.history.filter(isFactCheck)
  const other = feed.history.filter((c) => !isFactCheck(c))
  const tabs: { id: ClaimsTab; label: string; count?: number }[] = [
    { id: "now", label: "Now" },
    { id: "checked", label: "Checked", count: checked.length },
    { id: "other", label: "Other", count: other.length },
  ]
  const open = (id: string) => {
    feed.select(id)
    onTabChange("now")
  }
  const list = tab === "checked" ? checked : other

  return (
    <Panel className={cn("min-h-0", className)}>
      <div className="flex min-h-11 items-center justify-between gap-2 border-b border-line px-2 py-1.5 sm:px-3">
        <div role="tablist" aria-label="Claims" className="flex gap-0.5">
          {tabs.map((t) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={tab === t.id}
              onClick={() => onTabChange(t.id)}
              className={cn(
                "rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors",
                tab === t.id
                  ? "bg-brand/[0.07] text-brand"
                  : "text-ink-muted hover:text-ink"
              )}
            >
              {t.label}
              {t.count !== undefined ? (
                <span className="ml-1.5 font-mono text-[10px] text-ink-faint">
                  {t.count}
                </span>
              ) : null}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          {tab === "now" ? (
            <LiveStatus
              following={feed.following}
              pendingCount={feed.pendingCount}
              onFollowLive={feed.followLive}
            />
          ) : null}
          <ExportMenu disabled={claims.length === 0} onExport={onExport} />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto max-lg:max-h-[60svh]">
        {tab === "now" ? (
          feed.current ? (
            <ClaimDetail
              claim={feed.current}
              verifyState={verifications[feed.current.id]}
              earlier={
                feed.current.contradicts
                  ? claims.find((c) => c.id === feed.current?.contradicts)
                  : null
              }
              onOpenClaim={open}
              review={review.reviews[feed.current.id]}
              onDecide={(d) =>
                feed.current && review.setDecision(feed.current.id, d)
              }
              onNote={(n) => feed.current && review.setNote(feed.current.id, n)}
            />
          ) : (
            <p className="m-0 px-4 py-6 text-center text-[13px] leading-relaxed text-ink-faint">
              {EMPTY.now}
            </p>
          )
        ) : list.length ? (
          <ClaimList
            claims={list}
            verifications={verifications}
            reviews={review.reviews}
            showVerdict={tab === "checked"}
            onSelect={open}
          />
        ) : (
          <p className="m-0 px-4 py-5 text-center text-[13px] text-ink-faint">
            {EMPTY[tab]}
          </p>
        )}
      </div>
    </Panel>
  )
}
