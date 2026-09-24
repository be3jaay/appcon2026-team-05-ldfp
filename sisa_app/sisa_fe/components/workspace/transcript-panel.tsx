"use client"

import { Info, Search, X } from "lucide-react"
import { useEffect, useMemo, useRef, useState } from "react"

import { cn } from "@/lib/utils"
import { formatTime } from "@/lib/video"
import { VIDEO_COPY } from "@/constants/video"
import type { Verdict } from "@/lib/verification"
import type { useVideoTranscription } from "@/hooks/use-video-transcription"
import { ClaimLegend, ClaimText } from "@/components/claims/claim-text"
import { Panel, PanelHeader } from "@/components/workspace/panel"
import { InfoPopover } from "@/components/workspace/popover"

type Session = ReturnType<typeof useVideoTranscription>

export function TranscriptPanel({
  session,
  verdicts,
  onSelectClaim,
  className,
}: {
  session: Session
  verdicts?: Record<string, Verdict>
  /** Called when a highlighted claim is clicked. */
  onSelectClaim?: (id: string) => void
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
  const [searchOpen, setSearchOpen] = useState(false)
  const [query, setQuery] = useState("")
  const q = query.trim().toLowerCase()
  const shown = useMemo(
    () =>
      q ? segments.filter((s) => s.text.toLowerCase().includes(q)) : segments,
    [segments, q]
  )

  useEffect(() => {
    // Follow the live end, except while the reader is searching.
    if (!q) bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight })
  }, [segments, interimText, q])

  const empty =
    source === "mic"
      ? VIDEO_COPY.micReady
      : hasMedia
        ? VIDEO_COPY.emptyReady
        : VIDEO_COPY.emptyNoMedia
  // A time gutter only when lines have times (video); the mic has none.
  const timed = segments.some((s) => s.startTime !== undefined)
  const row = cn(
    "grid gap-x-2.5",
    timed ? "grid-cols-[34px_1fr]" : "grid-cols-1"
  )
  const textClass = "text-[15px] leading-[1.6] text-ink"

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
          <span className="flex items-center gap-0.5">
            <button
              type="button"
              aria-label="Search the transcript"
              aria-pressed={searchOpen}
              onClick={() => {
                setSearchOpen((o) => !o)
                setQuery("")
              }}
              className={cn(
                "rounded-full p-1 transition-colors hover:bg-canvas hover:text-brand-accent",
                searchOpen ? "text-brand-accent" : "text-ink-faint"
              )}
            >
              <Search className="h-4 w-4" />
            </button>
            <InfoPopover
              label="What the highlights mean"
              title="Highlights"
              triggerClassName="rounded-full p-1 text-ink-faint transition-colors hover:bg-canvas hover:text-brand-accent"
              trigger={<Info className="h-4 w-4" />}
            >
              <div className="flex flex-col gap-2.5 px-4 py-3 text-[12px] leading-relaxed text-ink-muted">
                <p className="m-0">
                  Detected claims are underlined by type. Click one to open it
                  in the claims panel; hover for a quick summary.
                </p>
                <ClaimLegend className="font-mono text-[10px] tracking-[0.04em]" />
                <p className="m-0">
                  The icon after a highlight is its verification verdict. Click
                  a time to jump the video there.
                </p>
              </div>
            </InfoPopover>
          </span>
        }
      />
      {searchOpen ? (
        <div className="flex items-center gap-2 border-b border-line px-4 py-1.5">
          <Search className="h-3.5 w-3.5 shrink-0 text-ink-faint" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                setSearchOpen(false)
                setQuery("")
              }
            }}
            placeholder="Search the transcript…"
            className="min-w-0 flex-1 bg-transparent py-1 text-[13px] text-ink placeholder:text-ink-faint focus:outline-none"
          />
          {q ? (
            <span className="shrink-0 font-mono text-[10px] text-ink-faint">
              {shown.length} {shown.length === 1 ? "line" : "lines"}
            </span>
          ) : null}
          <button
            type="button"
            aria-label="Close search"
            onClick={() => {
              setSearchOpen(false)
              setQuery("")
            }}
            className="rounded-full p-0.5 text-ink-faint hover:bg-canvas hover:text-ink"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      ) : null}
      {claimsError ? (
        <p
          className="m-0 border-b border-line bg-[#E4572E]/[0.05] px-4 py-1.5 text-[12px] text-[#a3361a]"
          title={claimsError}
        >
          Claim detection: {claimsError}
        </p>
      ) : null}
      <div
        ref={bodyRef}
        className="flex min-h-[200px] flex-1 flex-col gap-1.5 overflow-y-auto px-4 pt-3 pb-4 max-lg:max-h-[55svh]"
      >
        {isEmpty ? (
          <p className="m-0 self-center py-10 text-center text-[13px] text-ink-faint">
            {empty}
          </p>
        ) : q && shown.length === 0 ? (
          <p className="m-0 self-center py-10 text-center text-[13px] text-ink-faint">
            No lines contain “{query.trim()}”.
          </p>
        ) : (
          shown.map((seg, i) => {
            const newSpeaker = i === 0 || shown[i - 1].speaker !== seg.speaker
            return (
              <div key={seg.id} className={cn(newSpeaker && i > 0 && "mt-3")}>
                {newSpeaker ? (
                  <div className={row}>
                    {timed ? <span /> : null}
                    <span className="font-mono text-[11px] font-semibold tracking-[0.06em] text-brand">
                      SPEAKER {seg.speaker}
                    </span>
                  </div>
                ) : null}
                <div className={row}>
                  {timed ? (
                    seg.startTime !== undefined ? (
                      <button
                        type="button"
                        onClick={() => seekTo(seg.startTime)}
                        className="self-start pt-[5px] text-right font-mono text-[10px] text-ink-faint hover:text-brand-accent hover:underline"
                        title={VIDEO_COPY.seekTitle}
                      >
                        {formatTime(seg.startTime)}
                      </button>
                    ) : (
                      <span />
                    )
                  ) : null}
                  <ClaimText
                    text={seg.text}
                    claims={claimsBySegment[String(seg.id)]}
                    status={claimStatus[String(seg.id)]}
                    verdicts={verdicts}
                    onSelectClaim={onSelectClaim}
                    className={textClass}
                  />
                </div>
              </div>
            )
          })
        )}
        {interimText && !q ? (
          <div className={row}>
            {timed ? <span /> : null}
            <p className={cn(textClass, "m-0 text-ink-faint italic")}>
              {interimText}
              <span className="ml-[3px] inline-block h-[15px] w-[2px] translate-y-[3px] animate-pulse bg-brand" />
            </p>
          </div>
        ) : null}
      </div>
    </Panel>
  )
}
