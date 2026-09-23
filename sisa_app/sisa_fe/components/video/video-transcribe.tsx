"use client"

import { IBM_Plex_Mono, Newsreader } from "next/font/google"
import { useEffect, useRef, useState } from "react"

import { cn } from "@/lib/utils"
import { ClaimLegend, ClaimText } from "@/components/claims/claim-text"
import { resumeMediaElementAudio } from "@/lib/audio-inputs"
import { formatTime, youTubeEmbedUrl } from "@/lib/video"
import {
  VIDEO_CONTROL_LABELS,
  VIDEO_COPY,
  VIDEO_FILE_ACCEPT,
  VIDEO_FILE_FORMATS_HINT,
  VIDEO_SOURCE_TABS,
  YOUTUBE_IFRAME_ALLOW,
} from "@/constants/video"
import { useVideoTranscription } from "@/hooks/use-video-transcription"

const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"] })
const serif = Newsreader({ subsets: ["latin"] })

export function VideoTranscribe() {
  const {
    status,
    segments,
    interimText,
    error,
    stop,
    claimsBySegment,
    claimStatus,
    claimsError,
    live,
    busy,
    locked,
    hasMedia,
    isEmpty,
    source,
    selectSource,
    videoRef,
    videoUrl,
    videoName,
    loadFile,
    youtubeInput,
    setYoutubeInput,
    youtubeId,
    youtubeError,
    loadYouTube,
    startTranscribing,
    seekTo,
  } = useVideoTranscription()

  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight })
  }, [segments, interimText])

  return (
    <section className="flex flex-col rounded-[10px] border border-white/[0.07] bg-[#111113]">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/[0.07] px-5 py-3.5">
        <div className="flex items-center gap-3.5">
          <span
            className={cn(
              mono.className,
              "text-[11px] tracking-[0.12em] text-[#ECECEE]"
            )}
          >
            {VIDEO_COPY.title}
          </span>
          <div
            role="tablist"
            className="flex rounded-[6px] border border-white/[0.07] p-0.5"
          >
            {VIDEO_SOURCE_TABS.map((tab) => (
              <button
                key={tab.kind}
                type="button"
                role="tab"
                aria-selected={source === tab.kind}
                disabled={locked}
                onClick={() => selectSource(tab.kind)}
                className={cn(
                  "rounded-[4px] px-2.5 py-1 text-xs transition-colors disabled:cursor-not-allowed",
                  source === tab.kind
                    ? "bg-white/[0.08] text-[#ECECEE]"
                    : "text-[#85858D] hover:text-[#ECECEE]"
                )}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-3.5">
          <span
            className={cn(
              mono.className,
              "flex items-center gap-1.5 text-[11px] text-[#A1A1A8]"
            )}
          >
            <span
              className={cn(
                "h-[5px] w-[5px] rounded-full",
                live ? "animate-pulse bg-[#E8695C]" : "bg-[#6FA8E8]"
              )}
            />
            {live ? VIDEO_COPY.statusLive : VIDEO_COPY.statusIdle}
          </span>
          <button
            type="button"
            onClick={live ? stop : () => void startTranscribing()}
            disabled={busy || (!live && !hasMedia)}
            className="rounded-[5px] border border-white/[0.14] bg-transparent px-2.5 py-1 text-xs text-[#ECECEE] transition-colors hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {VIDEO_CONTROL_LABELS[status]}
          </button>
        </div>
      </div>

      {error ? (
        <div className="mx-5 mt-4 rounded-lg border border-[#E8695C] bg-[#E8695C]/10 px-3.5 py-2.5 text-[13px] text-[#ffb4b4]">
          {error}
        </div>
      ) : null}

      <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3">
          {/* Kept mounted so its audio graph survives switching tabs. */}
          <div
            className={cn(
              "relative aspect-video overflow-hidden rounded-lg bg-black",
              source !== "file" && "hidden"
            )}
          >
            <video
              ref={videoRef}
              src={videoUrl ?? undefined}
              controls
              playsInline
              onPlay={(e) => void resumeMediaElementAudio(e.currentTarget)}
              className={cn("h-full w-full", !videoUrl && "hidden")}
            />
            {!videoUrl ? (
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                onDragOver={(e) => {
                  e.preventDefault()
                  setDragging(true)
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDragging(false)
                  loadFile(e.dataTransfer.files[0])
                }}
                className={cn(
                  "absolute inset-0 flex flex-col items-center justify-center gap-2 border border-dashed text-center transition-colors",
                  dragging
                    ? "border-[#6FA8E8] bg-[#6FA8E8]/[0.06]"
                    : "border-white/[0.14] hover:bg-white/[0.03]"
                )}
              >
                <span className="text-sm text-[#ECECEE]">
                  {VIDEO_COPY.dropZone}
                </span>
                <span
                  className={cn(mono.className, "text-[11px] text-[#85858D]")}
                >
                  {VIDEO_FILE_FORMATS_HINT}
                </span>
              </button>
            ) : null}
          </div>

          {source === "file" && videoUrl ? (
            <div className="flex items-center justify-between gap-3">
              <span
                className={cn(
                  mono.className,
                  "truncate text-[11px] text-[#A1A1A8]"
                )}
              >
                {videoName}
              </span>
              <button
                type="button"
                disabled={locked}
                onClick={() => fileInputRef.current?.click()}
                className="shrink-0 text-xs text-[#85858D] hover:text-[#ECECEE] disabled:cursor-not-allowed disabled:opacity-50"
              >
                {VIDEO_COPY.changeVideo}
              </button>
            </div>
          ) : null}

          <input
            ref={fileInputRef}
            type="file"
            accept={VIDEO_FILE_ACCEPT}
            className="hidden"
            onChange={(e) => {
              loadFile(e.target.files?.[0])
              e.target.value = ""
            }}
          />

          {source === "youtube" ? (
            <>
              <form
                onSubmit={(e) => {
                  e.preventDefault()
                  loadYouTube()
                }}
                className="flex gap-2"
              >
                <input
                  value={youtubeInput}
                  onChange={(e) => setYoutubeInput(e.target.value)}
                  placeholder={VIDEO_COPY.youtubePlaceholder}
                  disabled={locked}
                  className="min-w-0 flex-1 rounded-[5px] border border-white/[0.14] bg-transparent px-3 py-1.5 text-sm text-[#ECECEE] placeholder:text-[#85858D] focus:border-[#6FA8E8] focus:outline-none"
                />
                <button
                  type="submit"
                  disabled={locked}
                  className="rounded-[5px] border border-white/[0.14] px-3 py-1.5 text-xs text-[#ECECEE] hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {VIDEO_COPY.youtubeLoad}
                </button>
              </form>
              {youtubeError ? (
                <p className="m-0 text-[13px] text-[#ffb4b4]">{youtubeError}</p>
              ) : null}
              <div className="aspect-video overflow-hidden rounded-lg bg-black">
                {youtubeId ? (
                  <iframe
                    src={youTubeEmbedUrl(youtubeId)}
                    title="YouTube video"
                    allow={YOUTUBE_IFRAME_ALLOW}
                    allowFullScreen
                    className="h-full w-full"
                  />
                ) : (
                  <div
                    className={cn(
                      mono.className,
                      "flex h-full items-center justify-center text-[13px] text-[#85858D]"
                    )}
                  >
                    {VIDEO_COPY.noVideo}
                  </div>
                )}
              </div>
              <p className="m-0 text-[12px] leading-relaxed text-[#85858D]">
                YouTube doesn&apos;t let websites read its audio directly. When
                you press{" "}
                <span className="text-[#ECECEE]">Start transcribing</span>,
                share <span className="text-[#ECECEE]">this tab</span> with{" "}
                <span className="text-[#ECECEE]">Share tab audio</span> turned
                on, then play the video. Works in Chrome and Edge.
              </p>
            </>
          ) : null}
        </div>

        <div className="flex min-h-[240px] flex-col rounded-lg border border-white/[0.07]">
          <div
            className={cn(
              mono.className,
              "border-b border-white/[0.07] px-4 py-2.5 text-[11px] tracking-[0.12em] text-[#A1A1A8]"
            )}
          >
            {VIDEO_COPY.transcriptTitle}
          </div>
          <div
            className={cn(
              mono.className,
              "flex flex-col gap-1 px-4 pt-2.5 text-[10px] tracking-[0.08em] text-[#85858D] uppercase"
            )}
          >
            <ClaimLegend />
            {claimsError ? (
              <span className="text-[#E8695C] normal-case" title={claimsError}>
                Claim detection: {claimsError}
              </span>
            ) : null}
          </div>
          <div
            ref={bodyRef}
            className="flex max-h-[460px] flex-1 flex-col gap-4 overflow-y-auto px-4 pt-3 pb-4"
          >
            {isEmpty ? (
              <p
                className={cn(
                  mono.className,
                  "m-0 self-center py-10 text-center text-[13px] text-[#85858D]"
                )}
              >
                {hasMedia ? VIDEO_COPY.emptyReady : VIDEO_COPY.emptyNoMedia}
              </p>
            ) : (
              segments.map((seg) => (
                <div key={seg.id} className="flex flex-col gap-1">
                  <div
                    className={cn(
                      mono.className,
                      "flex items-center gap-2 text-[11px] tracking-[0.08em]"
                    )}
                  >
                    {seg.startTime !== undefined ? (
                      <button
                        type="button"
                        onClick={() => seekTo(seg.startTime)}
                        className="text-[#6FA8E8] hover:underline"
                        title={VIDEO_COPY.seekTitle}
                      >
                        {formatTime(seg.startTime)}
                      </button>
                    ) : null}
                    <span className="text-[#ECECEE]">
                      SPEAKER {seg.speaker}
                    </span>
                  </div>
                  <ClaimText
                    text={seg.text}
                    claims={claimsBySegment[String(seg.id)]}
                    status={claimStatus[String(seg.id)]}
                    className={cn(
                      serif.className,
                      "text-[17px] leading-[1.5] text-[#D6D6DA]"
                    )}
                  />
                </div>
              ))
            )}
            {interimText ? (
              <p
                className={cn(
                  serif.className,
                  "m-0 text-[17px] leading-[1.5] text-[#85858D] italic"
                )}
              >
                {interimText}
                <span className="ml-[3px] inline-block h-[16px] w-[2px] translate-y-[3px] animate-pulse bg-[#ECECEE]" />
              </p>
            ) : null}
          </div>
        </div>
      </div>
    </section>
  )
}
