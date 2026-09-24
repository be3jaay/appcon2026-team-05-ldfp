"use client"

import { Dialog } from "@base-ui/react/dialog"
import { LoaderCircle, Sparkles, Volume2, X, Info } from "lucide-react"
import { useEffect, useRef, useState } from "react"

import type { SessionSummaryState } from "@/hooks/use-session-summary"

const STAGE_COPY = {
  waiting: "Tinatapos ang fact-check…",
  generating: "Binubuo ang buod…",
} as const

/** Plays the Tagalog summary as soon as the modal opens (the End click counts
 * as the user gesture browsers require). Falls back to the controls if blocked. */
function SummaryAudio({
  src,
  contentType,
}: {
  src: string
  contentType: string
}) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [blocked, setBlocked] = useState(false)

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    setBlocked(false)
    void audio.play().catch(() => setBlocked(true))
  }, [src])

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex items-center gap-3 rounded-lg border border-line bg-canvas px-3 py-2">
        <Volume2 className="h-4 w-4 shrink-0 text-brand-accent" />
        <audio
          ref={audioRef}
          controls
          autoPlay
          preload="auto"
          src={`data:${contentType};base64,${src}`}
          className="h-9 min-w-0 flex-1"
        >
          Hindi sinusuportahan ng browser ang audio playback.
        </audio>
      </div>
      {blocked ? (
        <p className="m-0 text-[11px] text-ink-faint">
          Hinarang ng browser ang autoplay — pindutin ang play para pakinggan.
        </p>
      ) : null}
    </div>
  )
}

function SummaryBody({ summary }: { summary: SessionSummaryState }) {
  if (summary.state === "waiting" || summary.state === "generating") {
    return (
      <div className="flex flex-col items-center gap-3 py-8 text-center">
        <LoaderCircle className="h-6 w-6 animate-spin text-brand-accent" />
        <p className="m-0 text-sm font-medium text-ink">
          {STAGE_COPY[summary.state]}
        </p>
        <p className="m-0 max-w-sm text-[13px] leading-relaxed text-ink-muted">
          Hinihintay munang matapos ang lahat ng claim at ebidensya bago buuin
          ang Tagalog na paliwanag ng buong sesyon.
        </p>
      </div>
    )
  }

  if (summary.state === "failed") {
    return (
      <div className="rounded-lg border border-[#E4572E]/40 bg-[#E4572E]/[0.06] px-3 py-2 text-[13px] text-[#a3361a]">
        Hindi nagawa ang pangwakas na buod: {summary.message}
      </div>
    )
  }

  if (summary.state === "done") {
    return (
      <div className="flex flex-col gap-3">
        {summary.result.audio_base64 ? (
          <SummaryAudio
            src={summary.result.audio_base64}
            contentType={summary.result.audio_content_type}
          />
        ) : (
          <p className="m-0 text-xs text-ink-muted">
            Hindi available ang audio ngayon
            {summary.result.audio_error
              ? `: ${summary.result.audio_error}`
              : "."}
          </p>
        )}
        <p className="m-0 text-sm leading-6 whitespace-pre-line text-ink">
          {summary.result.summary_text}
        </p>
      </div>
    )
  }

  return null
}

/**
 * End-of-session Tagalog analysis. Opens itself when the summary starts after
 * Stop / End, and stays reachable through a small toolbar button.
 */
export function SessionSummary({ summary }: { summary: SessionSummaryState }) {
  const [open, setOpen] = useState(false)
  const active = summary.state !== "idle"

  useEffect(() => {
    // Opens once per session: when work starts, and closes when a new one begins.
    setOpen(active)
  }, [active])

  if (!active) return null

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger
        title={
          summary.state === "done"
            ? "Tingnan ang pangwakas na buod"
            : summary.state === "failed"
              ? "Hindi nagawa ang buod — tingnan ang detalye"
              : "Binubuo ang pangwakas na buod…"
        }
        className="flex items-center gap-1.5 rounded-lg border border-line bg-white px-2.5 py-1.5 text-xs font-medium text-brand transition-colors hover:border-brand-accent/50"
      >
        {summary.state === "done" || summary.state === "failed" ? (
          <Sparkles className="h-3.5 w-3.5 text-brand-accent" />
        ) : (
          <LoaderCircle className="h-3.5 w-3.5 animate-spin text-brand-accent" />
        )}
        <span className="hidden sm:inline">Buod</span>
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-40 bg-ink/40 transition-opacity data-[ending-style]:opacity-0 data-[starting-style]:opacity-0" />
        <Dialog.Popup className="fixed inset-x-0 bottom-0 z-50 flex max-h-[85svh] flex-col rounded-t-2xl bg-white shadow-2xl transition-transform duration-200 data-[ending-style]:translate-y-full data-[starting-style]:translate-y-full sm:inset-x-auto sm:top-1/2 sm:left-1/2 sm:w-[540px] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl">
          <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-line sm:hidden" />
          <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
            <Dialog.Title className="m-0 flex items-center gap-2 text-[13px] font-semibold tracking-[0.08em] text-brand uppercase">
              <Info className="h-4 w-4 text-brand-accent" />
              Pangwakas na buod
            </Dialog.Title>
            <Dialog.Close
              aria-label="Isara"
              className="rounded-full p-1 text-ink-muted hover:bg-canvas"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 pb-[max(1rem,env(safe-area-inset-bottom))]">
            <SummaryBody summary={summary} />
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
