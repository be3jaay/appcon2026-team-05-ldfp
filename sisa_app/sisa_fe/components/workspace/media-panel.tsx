"use client"

import { CircleHelp, Mic, Upload } from "lucide-react"
import { useEffect, useRef, useState, type ReactNode } from "react"

import { cn } from "@/lib/utils"
import { resumeMediaElementAudio } from "@/lib/audio-inputs"
import { youTubeEmbedUrl } from "@/lib/video"
import {
  VIDEO_CONTROL_LABELS,
  VIDEO_COPY,
  VIDEO_FILE_ACCEPT,
  VIDEO_FILE_FORMATS_HINT,
  VIDEO_SOURCE_TABS,
  YOUTUBE_IFRAME_ALLOW,
} from "@/constants/video"
import type { useVideoTranscription } from "@/hooks/use-video-transcription"
import { Panel } from "@/components/workspace/panel"
import { InfoPopover } from "@/components/workspace/popover"

type Session = ReturnType<typeof useVideoTranscription>

const WAVE_BARS = 32

function MicStage({ live }: { live: boolean }) {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    if (!live) return
    const id = setInterval(() => setTick((t) => t + 1), 90)
    return () => clearInterval(id)
  }, [live])

  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 bg-brand text-white">
      <span
        className={cn(
          "flex h-14 w-14 items-center justify-center rounded-full",
          live ? "bg-white text-brand" : "bg-white/10 text-white"
        )}
      >
        <Mic className="h-6 w-6" />
      </span>
      <div className="flex h-8 items-center gap-[3px]">
        {Array.from({ length: WAVE_BARS }, (_, i) => (
          <span
            key={i}
            className="w-[3px] rounded-full bg-white/70 transition-[height] duration-100"
            style={{
              height: live
                ? `${4 + Math.abs(Math.sin(i * 1.7 + (tick * 90) / 110)) * 22 * (0.45 + 0.55 * Math.abs(Math.sin(i * 0.5 + (tick * 90) / 380)))}px`
                : "4px",
            }}
          />
        ))}
      </div>
      <p className="m-0 px-6 text-center text-sm text-white/80">
        {live ? VIDEO_COPY.micLive : VIDEO_COPY.micReady}
      </p>
    </div>
  )
}

export function MediaPanel({
  session,
  actions,
  overlay,
}: {
  session: Session
  /** Extra toolbar buttons shown before Start/Stop (e.g. the session summary). */
  actions?: ReactNode
  /** Shown over whichever stage is visible (video, YouTube or mic), e.g. claim alerts. */
  overlay?: ReactNode
}) {
  const {
    status,
    error,
    stop,
    live,
    busy,
    locked,
    hasMedia,
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
  } = session

  const [dragging, setDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  return (
    <Panel className="overflow-hidden">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2 sm:px-4">
        <div
          role="tablist"
          className="flex min-w-0 rounded-lg bg-canvas p-0.5"
          aria-label="Audio source"
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
                "rounded-md px-2.5 py-1 text-xs font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed sm:px-3",
                source === tab.kind
                  ? "bg-white text-brand shadow-sm"
                  : "text-ink-muted hover:text-ink"
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {actions}
          <button
            type="button"
            onClick={live ? stop : () => void startTranscribing()}
            disabled={busy || (!live && !hasMedia)}
            className={cn(
              "shrink-0 rounded-lg px-3.5 py-1.5 text-xs font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
              live
                ? "bg-[#E4572E] text-white hover:bg-[#cf4a23]"
                : "bg-brand text-white hover:bg-brand-deep"
            )}
          >
            {VIDEO_CONTROL_LABELS[status]}
          </button>
        </div>
      </div>

      {error ? (
        <div className="mx-3 mt-3 rounded-lg border border-[#E4572E]/40 bg-[#E4572E]/[0.06] px-3 py-2 text-[13px] text-[#a3361a] sm:mx-4">
          {error}
        </div>
      ) : null}

      <div className="flex flex-col gap-2.5 p-3 sm:p-4">
        {/* Kept mounted so its audio graph survives switching tabs. */}
        <div
          className={cn(
            "relative aspect-video overflow-hidden rounded-lg bg-ink",
            source !== "file" && "hidden"
          )}
        >
          {source === "file" ? overlay : null}
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
                "absolute inset-0 flex flex-col items-center justify-center gap-2 border-2 border-dashed bg-canvas text-center transition-colors",
                dragging
                  ? "border-brand-accent bg-brand-sky/10"
                  : "border-line hover:border-brand-accent/50"
              )}
            >
              <Upload className="h-6 w-6 text-brand-accent" />
              <span className="text-sm font-medium text-ink">
                {VIDEO_COPY.dropZone}
              </span>
              <span className="font-mono text-[11px] text-ink-faint">
                {VIDEO_FILE_FORMATS_HINT}
              </span>
            </button>
          ) : null}
        </div>

        {source === "file" && videoUrl ? (
          <div className="flex items-center justify-between gap-3">
            <span className="truncate font-mono text-[11px] text-ink-muted">
              {videoName}
            </span>
            <button
              type="button"
              disabled={locked}
              onClick={() => fileInputRef.current?.click()}
              className="shrink-0 text-xs font-medium text-brand-accent hover:underline disabled:cursor-not-allowed disabled:opacity-50"
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
                className="min-w-0 flex-1 rounded-lg border border-line bg-white px-3 py-1.5 text-sm text-ink placeholder:text-ink-faint focus:border-brand-accent focus:outline-none"
              />
              <button
                type="submit"
                disabled={locked}
                className="rounded-lg border border-line px-3 py-1.5 text-xs font-medium text-brand hover:bg-canvas disabled:cursor-not-allowed disabled:opacity-50"
              >
                {VIDEO_COPY.youtubeLoad}
              </button>
              <InfoPopover
                label="How YouTube audio works"
                title="How YouTube audio works"
                triggerClassName="shrink-0 rounded-lg px-1.5 text-ink-faint transition-colors hover:bg-canvas hover:text-brand-accent"
                trigger={<CircleHelp className="h-4 w-4" />}
              >
                <p className="m-0 px-4 py-3 text-[12px] leading-relaxed text-ink-muted">
                  YouTube doesn&apos;t let websites read its audio directly.
                  When you press <b className="text-ink">Start</b>, share{" "}
                  <b className="text-ink">this tab</b> with{" "}
                  <b className="text-ink">Share tab audio</b> turned on, then
                  play the video. Works in Chrome and Edge.
                </p>
              </InfoPopover>
            </form>
            {youtubeError ? (
              <p className="m-0 text-[13px] text-[#a3361a]">{youtubeError}</p>
            ) : null}
            <div className="relative aspect-video overflow-hidden rounded-lg bg-ink">
              {overlay}
              {youtubeId ? (
                <iframe
                  src={youTubeEmbedUrl(youtubeId)}
                  title="YouTube video"
                  allow={YOUTUBE_IFRAME_ALLOW}
                  allowFullScreen
                  className="h-full w-full"
                />
              ) : (
                <div className="flex h-full items-center justify-center bg-canvas font-mono text-[13px] text-ink-faint">
                  {VIDEO_COPY.noVideo}
                </div>
              )}
            </div>
          </>
        ) : null}

        {source === "mic" ? (
          <div className="relative aspect-video overflow-hidden rounded-lg max-sm:aspect-[16/7]">
            {overlay}
            <MicStage live={live} />
          </div>
        ) : null}
      </div>
    </Panel>
  )
}
