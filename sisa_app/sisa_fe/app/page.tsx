"use client"

import { useState } from "react"

import { cn } from "@/lib/utils"
import { TranscribeCard } from "@/components/transcribe/transcribe-card"
import { VideoTranscribe } from "@/components/video/video-transcribe"

type Mode = "video" | "mic"

const MODES: { mode: Mode; label: string }[] = [
  { mode: "video", label: "Video" },
  { mode: "mic", label: "Microphone" },
]

export default function Page() {
  const [mode, setMode] = useState<Mode>("video")

  return (
    <div className="min-h-svh bg-[#0A0A0B] p-4 sm:p-6">
      <div
        className={cn(
          "mx-auto flex flex-col gap-4",
          mode === "video" ? "max-w-6xl" : "max-w-3xl"
        )}
      >
        <nav className="flex gap-1 self-start rounded-[8px] border border-white/[0.07] bg-[#111113] p-1">
          {MODES.map((m) => (
            <button
              key={m.mode}
              type="button"
              onClick={() => setMode(m.mode)}
              className={cn(
                "rounded-[5px] px-3 py-1.5 text-xs transition-colors",
                mode === m.mode
                  ? "bg-white/[0.08] text-[#ECECEE]"
                  : "text-[#85858D] hover:text-[#ECECEE]"
              )}
            >
              {m.label}
            </button>
          ))}
        </nav>
        {mode === "video" ? <VideoTranscribe /> : <TranscribeCard />}
      </div>
    </div>
  )
}
