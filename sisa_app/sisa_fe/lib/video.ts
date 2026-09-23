import {
  VIDEO_FILE_MIME_PREFIXES,
  YOUTUBE_EMBED_BASE_URL,
  YOUTUBE_EMBED_PARAMS,
  YOUTUBE_ID_PATTERN,
  YOUTUBE_PATH_ID_PATTERN,
} from "@/constants/video"

export function parseYouTubeId(input: string): string | null {
  const value = input.trim()
  if (YOUTUBE_ID_PATTERN.test(value)) return value
  try {
    const url = new URL(value)
    if (url.hostname === "youtu.be") return url.pathname.slice(1, 12) || null
    if (!url.hostname.endsWith("youtube.com")) return null
    const v = url.searchParams.get("v")
    if (v) return v
    return url.pathname.match(YOUTUBE_PATH_ID_PATTERN)?.[1] ?? null
  } catch {
    return null
  }
}

export function youTubeEmbedUrl(id: string) {
  return `${YOUTUBE_EMBED_BASE_URL}/${id}?${YOUTUBE_EMBED_PARAMS}`
}

export function isPlayableFile(file: File) {
  return VIDEO_FILE_MIME_PREFIXES.some((prefix) => file.type.startsWith(prefix))
}

export function formatTime(seconds: number) {
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = String(total % 60).padStart(2, "0")
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`
}
