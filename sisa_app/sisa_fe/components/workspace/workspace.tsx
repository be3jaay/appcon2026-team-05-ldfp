"use client"

import { useMemo } from "react"

import { verdictOf } from "@/lib/verification"
import { useClaimFeed } from "@/hooks/use-claim-feed"
import { useClaimVerification } from "@/hooks/use-claim-verification"
import { useSessionSummary } from "@/hooks/use-session-summary"
import { useVideoTranscription } from "@/hooks/use-video-transcription"
import { AppHeader } from "@/components/workspace/app-header"
import {
  ClaimHistoryBadge,
  ClaimHistoryList,
} from "@/components/workspace/claim-history"
import { CurrentClaim } from "@/components/workspace/current-claim"
import { MediaPanel } from "@/components/workspace/media-panel"
import { SessionSummary } from "@/components/workspace/session-summary"
import { TranscriptPanel } from "@/components/workspace/transcript-panel"
import { TrustedSources } from "@/components/workspace/trusted-sources"

/**
 * Desktop: media + transcript on the left; current claim, history and
 * sources in a sticky right column.
 * Mobile: compact media, current claim, history badge (opens a sheet),
 * transcript, then collapsible sources.
 */
export function Workspace() {
  const session = useVideoTranscription()
  const feed = useClaimFeed(session.claims, session.claimStatus)
  // Context sent with each claim: the line before, its own line and the next one when it
  // has arrived (a place or contractor is often named a sentence before or after the figure).
  const segmentText = useMemo(
    () =>
      Object.fromEntries(
        session.segments.map((s, i) => [
          String(s.id),
          [session.segments[i - 1]?.text, s.text, session.segments[i + 1]?.text]
            .filter(Boolean)
            .join(" "),
        ])
      ),
    [session.segments]
  )
  const verifications = useClaimVerification(session.claims, segmentText)
  const summary = useSessionSummary({
    status: session.status,
    segments: session.segments,
    claims: session.claims,
    claimStatus: session.claimStatus,
    verifications,
  })
  const verdicts = useMemo(
    () =>
      Object.fromEntries(
        session.claims.map((c) => [c.id, verdictOf(c, verifications[c.id])])
      ),
    [session.claims, verifications]
  )
  const history = {
    claims: feed.history,
    verifications,
    onSelect: feed.select,
  }

  const currentClaim = (compact: boolean, className?: string) => (
    <CurrentClaim
      claim={feed.current}
      verifyState={feed.current ? verifications[feed.current.id] : undefined}
      following={feed.following}
      pendingCount={feed.pendingCount}
      onFollowLive={feed.followLive}
      compact={compact}
      className={className}
    />
  )

  return (
    <div className="min-h-svh bg-canvas text-ink">
      <AppHeader live={session.live} claimCount={session.claims.length} />

      <main className="mx-auto grid max-w-7xl grid-cols-1 gap-3 px-3 py-3 sm:gap-4 sm:px-6 sm:py-5 lg:grid-cols-[minmax(0,1fr)_380px] lg:gap-5">
        <div className="flex min-w-0 flex-col gap-3 sm:gap-4">
          <MediaPanel session={session} />

          <div className="flex flex-col gap-3 lg:hidden">
            {currentClaim(true)}
            <ClaimHistoryBadge {...history} />
          </div>

          <TranscriptPanel
            session={session}
            verdicts={verdicts}
            className="lg:h-[460px]"
          />

          <SessionSummary summary={summary} />

          <TrustedSources collapsible className="lg:hidden" />
        </div>

        <aside className="hidden min-h-0 flex-col gap-4 lg:sticky lg:top-5 lg:flex lg:max-h-[calc(100svh-2.5rem)] lg:self-start lg:overflow-y-auto">
          {currentClaim(false)}
          <ClaimHistoryList {...history} className="h-[380px] shrink-0" />
          <TrustedSources className="shrink-0" />
        </aside>
      </main>
    </div>
  )
}
