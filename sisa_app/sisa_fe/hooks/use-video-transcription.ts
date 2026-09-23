"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import {
  DEFAULT_VIDEO_SOURCE,
  VIDEO_COPY,
  type VideoSourceKind,
} from "@/constants/video"
import {
  disposeMediaElementAudio,
  mediaElementInput,
  tabAudioInput,
} from "@/lib/audio-inputs"
import { isPlayableFile, parseYouTubeId } from "@/lib/video"
import { useSonioxTranscription } from "@/hooks/use-soniox-transcription"

export function useVideoTranscription() {
  const transcription = useSonioxTranscription()
  const { status, segments, interimText, start } = transcription

  const [source, setSource] = useState<VideoSourceKind>(DEFAULT_VIDEO_SOURCE)
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [videoName, setVideoName] = useState("")
  const [youtubeInput, setYoutubeInput] = useState("")
  const [youtubeId, setYoutubeId] = useState<string | null>(null)
  const [youtubeError, setYoutubeError] = useState<string | null>(null)

  const videoRef = useRef<HTMLVideoElement>(null)

  const live = status === "live"
  const busy = status === "connecting" || status === "stopping"
  const locked = live || busy
  const hasMedia = source === "file" ? Boolean(videoUrl) : Boolean(youtubeId)
  const isEmpty = segments.length === 0 && !interimText

  useEffect(() => {
    if (!videoUrl) return
    return () => URL.revokeObjectURL(videoUrl)
  }, [videoUrl])

  useEffect(() => {
    const video = videoRef.current
    return () => {
      if (video) void disposeMediaElementAudio(video)
    }
  }, [])

  const selectSource = useCallback(
    (kind: VideoSourceKind) => {
      if (!locked) setSource(kind)
    },
    [locked]
  )

  const loadFile = useCallback(
    (file: File | undefined) => {
      if (!file || locked || !isPlayableFile(file)) return
      setVideoName(file.name)
      setVideoUrl(URL.createObjectURL(file))
    },
    [locked]
  )

  const loadYouTube = useCallback(() => {
    const id = parseYouTubeId(youtubeInput)
    setYoutubeError(id ? null : VIDEO_COPY.youtubeInvalid)
    if (id) setYoutubeId(id)
  }, [youtubeInput])

  const startTranscribing = useCallback(async () => {
    if (source === "youtube") {
      await start(tabAudioInput)
      return
    }
    const video = videoRef.current
    if (!video) return
    await start(mediaElementInput(video))
    void video.play().catch(() => {})
  }, [source, start])

  const seekTo = useCallback(
    (time: number | undefined) => {
      const video = videoRef.current
      if (source !== "file" || !video || time === undefined) return
      video.currentTime = time
    },
    [source]
  )

  return {
    ...transcription,
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
  }
}
