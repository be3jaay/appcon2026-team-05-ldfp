"use client"

import { useEffect, useRef, type ReactNode } from "react"

import { cn } from "@/lib/utils"
import { formatTime } from "@/lib/video"
import { VIDEO_COPY } from "@/constants/video"
import type { Verdict } from "@/lib/verification"
import type { useVideoTranscription } from "@/hooks/use-video-transcription"
import { ClaimLegend, ClaimText } from "@/components/claims/claim-text"
import { Panel, PanelHeader } from "@/components/workspace/panel"

type Session = ReturnType<typeof useVideoTranscription>

export function TranscriptPanel({
  session,
  verdicts,
  top,
  className,
}: {
  session: Session
  verdicts?: Record<string, Verdict>
  /** Rendered above the transcript lines (e.g. the mobile history badge). */
  top?: ReactNode
  className?: string
}) {
  const {
    segments,
    interimText,
    claimsBySegment,
    claimStatus,
    claimsError,
    hasMedia,
    isEmpty,
    source,
    seekTo,
    live,
  } = session
  const bodyRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight })
  }, [segments, interimText])

  const empty =
    source === "mic"
      ? VIDEO_COPY.micReady
      : hasMedia
        ? VIDEO_COPY.emptyReady
        : VIDEO_COPY.emptyNoMedia

  return (
    <Panel className={cn("min-h-0", className)}>
      <PanelHeader
        title={
          <span className="flex items-center gap-2">
            Live transcript
            {live ? (
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-[#E4572E]" />
            ) : null}
          </span>
        }
        aside={
          <span className="font-mono text-[10px] text-ink-faint">
            Soniox · EN
          </span>
        }
      />
      <div className="flex flex-col gap-1.5 border-b border-line px-4 py-2">
        <ClaimLegend className="font-mono text-[10px] tracking-[0.04em] text-ink-muted" />
        {claimsError ? (
          <span className="text-[12px] text-[#a3361a]" title={claimsError}>
            Claim detection: {claimsError}
          </span>
        ) : null}
      </div>
      {top ? <div className="px-4 pt-3">{top}</div> : null}
      <div
        ref={bodyRef}
        className="flex min-h-[200px] flex-1 flex-col gap-4 overflow-y-auto px-4 pt-3 pb-4 max-lg:max-h-[55svh]"
      >
        {isEmpty ? (
          <p className="m-0 self-center py-10 text-center text-[13px] text-ink-faint">
            {empty}
          </p>
        ) : (
          segments.map((seg) => (
            <div key={seg.id} className="flex flex-col gap-0.5">
              <div className="flex items-center gap-2 font-mono text-[11px] tracking-[0.06em]">
                {seg.startTime !== undefined ? (
                  <button
                    type="button"
                    onClick={() => seekTo(seg.startTime)}
                    className="text-brand-accent hover:underline"
                    title={VIDEO_COPY.seekTitle}
                  >
                    {formatTime(seg.startTime)}
                  </button>
                ) : null}
                <span className="font-semibold text-brand">
                  SPEAKER {seg.speaker}
                </span>
              </div>
              <ClaimText
                text={seg.text}
                claims={claimsBySegment[String(seg.id)]}
                status={claimStatus[String(seg.id)]}
                verdicts={verdicts}
                className="text-[15px] leading-[1.6] text-ink sm:text-[16px]"
              />
            </div>
          ))
        )}
        {interimText ? (
          <p className="m-0 text-[15px] leading-[1.6] text-ink-faint italic sm:text-[16px]">
            {interimText}
            <span className="ml-[3px] inline-block h-[15px] w-[2px] translate-y-[3px] animate-pulse bg-brand" />
          </p>
        ) : null}
      </div>
    </Panel>
  )
}
