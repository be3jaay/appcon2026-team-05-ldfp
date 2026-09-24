"use client"

import { useMemo, useState } from "react"

import { verdictOf } from "@/lib/verification"
import {
  downloadFile,
  exportName,
  sessionJson,
  sessionMarkdown,
} from "@/lib/export"
import { useClaimFeed } from "@/hooks/use-claim-feed"
import { useClaimAlerts } from "@/hooks/use-claim-alerts"
import { useClaimReview } from "@/hooks/use-claim-review"
import { useClaimVerification } from "@/hooks/use-claim-verification"
import { useSessionSummary } from "@/hooks/use-session-summary"
import { useVideoTranscription } from "@/hooks/use-video-transcription"
import { AppHeader } from "@/components/workspace/app-header"
import { ClaimAlertOverlay } from "@/components/workspace/claim-alert"
import {
  ClaimsPanel,
  type ClaimsTab,
} from "@/components/workspace/claims-panel"
import { MediaPanel } from "@/components/workspace/media-panel"
import { SessionSummary } from "@/components/workspace/session-summary"
import { TranscriptPanel } from "@/components/workspace/transcript-panel"

/**
 * Three blocks. Desktop: media and the claims panel on the left, the live
 * transcript filling the right column; the page itself doesn't scroll.
 * Mobile: media, claims panel, transcript. Sources sit behind a header button.
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
  const review = useClaimReview(session.claims)
  const exportSession = (format: "md" | "json") => {
    const data = {
      segments: session.segments,
      claims: session.claims,
      verifications,
      reviews: review.reviews,
    }
    if (format === "md")
      downloadFile(exportName("md"), sessionMarkdown(data), "text/markdown")
    else downloadFile(exportName("json"), sessionJson(data), "application/json")
  }
  const [claimsTab, setClaimsTab] = useState<ClaimsTab>("now")
  const openClaim = (id: string) => {
    feed.select(id)
    setClaimsTab("now")
  }
  const alerts = useClaimAlerts(session.claims, verdicts)

  return (
    <div className="flex min-h-svh flex-col bg-canvas text-ink lg:h-svh">
      <AppHeader live={session.live} claimCount={session.claims.length} />

      <main className="mx-auto grid w-full max-w-7xl flex-1 grid-cols-1 content-start gap-3 px-3 py-3 sm:gap-4 sm:px-6 sm:py-4 lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_minmax(360px,420px)] lg:content-stretch lg:gap-5">
        <div className="flex min-w-0 flex-col gap-3 sm:gap-4 lg:min-h-0 lg:overflow-y-auto">
          <MediaPanel
            session={session}
            actions={<SessionSummary summary={summary} />}
            overlay={
              <ClaimAlertOverlay
                alert={alerts.alert}
                onOpen={openClaim}
                onDismiss={alerts.dismiss}
              />
            }
          />
          <ClaimsPanel
            feed={feed}
            claims={session.claims}
            verifications={verifications}
            review={review}
            onExport={exportSession}
            tab={claimsTab}
            onTabChange={setClaimsTab}
            className="lg:min-h-[220px] lg:flex-1"
          />
        </div>

        <TranscriptPanel
          session={session}
          verdicts={verdicts}
          onSelectClaim={openClaim}
          className="lg:h-full"
        />
      </main>
    </div>
  )
}
