"use client"

import { IBM_Plex_Mono, Newsreader } from "next/font/google"
import { useEffect, useMemo, useRef, useState } from "react"

import { cn } from "@/lib/utils"
import {
  useSonioxTranscription,
  type TranscriptStatus,
} from "@/hooks/use-soniox-transcription"

const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"] })
const serif = Newsreader({ subsets: ["latin"] })

const WAVE_BAR_COUNT = 28
const WAVE_TICK_MS = 90

function waveBarHeight(index: number, t: number, live: boolean) {
  if (!live) return 3
  return (
    3 +
    Math.abs(Math.sin(index * 1.7 + t / 110)) *
      13 *
      (0.45 + 0.55 * Math.abs(Math.sin(index * 0.5 + t / 380)))
  )
}

function controlLabel(status: TranscriptStatus) {
  if (status === "live") return "Stop"
  if (status === "connecting") return "Connecting…"
  if (status === "stopping") return "Stopping…"
  return "Start listening"
}

export function TranscribeCard() {
  const { status, segments, interimText, error, start, stop } =
    useSonioxTranscription()
  const bodyRef = useRef<HTMLDivElement>(null)
  const [tick, setTick] = useState(0)

  const live = status === "live"
  const busy = status === "connecting" || status === "stopping"
  const isEmpty = segments.length === 0 && !interimText

  useEffect(() => {
    if (!live) return
    const id = setInterval(() => setTick((t) => t + 1), WAVE_TICK_MS)
    return () => clearInterval(id)
  }, [live])

  useEffect(() => {
    bodyRef.current?.scrollTo({ top: bodyRef.current.scrollHeight })
  }, [segments, interimText])

  const bars = useMemo(
    () => Array.from({ length: WAVE_BAR_COUNT }, (_, i) => i),
    []
  )

  return (
    <section className="flex flex-col rounded-[10px] border border-white/[0.07] bg-[#111113]">
      <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-3.5">
        <div className="flex items-center gap-3.5">
          <span
            className={cn(
              mono.className,
              "text-[11px] tracking-[0.12em] text-[#ECECEE]"
            )}
          >
            LIVE TRANSCRIPT
          </span>
          <div className="flex h-[18px] items-center gap-[2px]">
            {bars.map((i) => (
              <span
                key={i}
                className="w-[2px] rounded-[1px] bg-[#A1A1A8] transition-[height] duration-100"
                style={{ height: `${waveBarHeight(i, tick * WAVE_TICK_MS, live)}px` }}
              />
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
            <span className="h-[5px] w-[5px] rounded-full bg-[#6FA8E8]" />
            Soniox · Live transcription · EN
          </span>
          <button
            type="button"
            onClick={live ? stop : start}
            disabled={busy}
            className="rounded-[5px] border border-white/[0.14] bg-transparent px-2.5 py-1 text-xs text-[#ECECEE] transition-colors hover:bg-white/[0.06] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {controlLabel(status)}
          </button>
        </div>
      </div>

      {error ? (
        <div className="mx-5 mt-4 rounded-lg border border-[#E8695C] bg-[#E8695C]/10 px-3.5 py-2.5 text-[13px] text-[#ffb4b4]">
          {error}
        </div>
      ) : null}

      <div
        ref={bodyRef}
        className="flex max-h-[320px] min-h-[180px] flex-col gap-[18px] overflow-y-auto px-5 pt-4 pb-5"
        style={{
          maskImage: "linear-gradient(180deg,transparent 0,#000 48px)",
          WebkitMaskImage: "linear-gradient(180deg,transparent 0,#000 48px)",
        }}
      >
        {isEmpty ? (
          <p
            className={cn(
              mono.className,
              "m-0 self-center py-10 text-[13px] text-[#85858D]"
            )}
          >
            Transcript will appear here once you start speaking…
          </p>
        ) : (
          segments.map((seg) => (
            <div key={seg.id} className="grid grid-cols-[104px_minmax(0,1fr)] gap-4">
              <span
                className={cn(
                  mono.className,
                  "pt-1 text-[11px] tracking-[0.08em] text-[#ECECEE]"
                )}
              >
                SPEAKER {seg.speaker}
              </span>
              <p
                className={cn(
                  serif.className,
                  "m-0 text-[20px] leading-[1.5] text-[#D6D6DA]"
                )}
              >
                {seg.text}
              </p>
            </div>
          ))
        )}
        {interimText ? (
          <div className="grid grid-cols-[104px_minmax(0,1fr)] gap-4">
            <span aria-hidden className="pt-1" />
            <p
              className={cn(
                serif.className,
                "m-0 text-[20px] leading-[1.5] text-[#85858D] italic"
              )}
            >
              {interimText}
              <span className="ml-[3px] inline-block h-[18px] w-[2px] translate-y-[3px] animate-pulse bg-[#ECECEE]" />
            </p>
          </div>
        ) : null}
      </div>
    </section>
  )
}
