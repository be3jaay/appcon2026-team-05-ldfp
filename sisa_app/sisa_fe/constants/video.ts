import type { TranscriptStatus } from "@/hooks/use-soniox-transcription"

export type VideoSourceKind = "file" | "youtube" | "mic"

export const VIDEO_SOURCE_TABS: { kind: VideoSourceKind; label: string }[] = [
  { kind: "file", label: "Video file" },
  { kind: "youtube", label: "YouTube" },
  { kind: "mic", label: "Microphone" },
]

export const DEFAULT_VIDEO_SOURCE: VideoSourceKind = "file"

export const VIDEO_FILE_ACCEPT = "video/*,audio/*"
export const VIDEO_FILE_MIME_PREFIXES = ["video/", "audio/"]
export const VIDEO_FILE_FORMATS_HINT = "MP4 · WEBM · MOV"

export const YOUTUBE_EMBED_BASE_URL = "https://www.youtube.com/embed"
export const YOUTUBE_EMBED_PARAMS = "rel=0"
export const YOUTUBE_IFRAME_ALLOW =
  "autoplay; encrypted-media; picture-in-picture"
export const YOUTUBE_ID_PATTERN = /^[\w-]{11}$/
export const YOUTUBE_PATH_ID_PATTERN = /^\/(?:embed|live|shorts)\/([\w-]{11})/

export const VIDEO_CONTROL_LABELS: Record<TranscriptStatus, string> = {
  idle: "Start",
  connecting: "Connecting…",
  live: "End & summarize",
  stopping: "Ending…",
  error: "Start",
}

export const VIDEO_COPY = {
  title: "WATCH & TRANSCRIBE",
  transcriptTitle: "TRANSCRIPT",
  statusLive: "Transcribing video audio",
  statusIdle: "Soniox · TL/EN",
  dropZone: "Drop a video here, or click to choose",
  changeVideo: "Change video",
  youtubePlaceholder: "Paste a YouTube link (video or live)",
  youtubeLoad: "Load",
  youtubeInvalid: "That doesn't look like a YouTube link.",
  noVideo: "No video loaded",
  emptyNoMedia: "Load a video to get started…",
  emptyReady: "Press Start to follow what's being said…",
  micReady: "Press Start and speak. Claims are detected as you talk.",
  micLive: "Listening…",
  seekTitle: "Jump to this moment",
} as const
