"use client"

import { useCallback, useRef, useState } from "react"

const SONIOX_WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
const END_TOKEN = "<end>"

const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ?? "http://localhost:8000"

export type TranscriptStatus =
  | "idle"
  | "connecting"
  | "live"
  | "stopping"
  | "error"

export interface TranscriptSegment {
  id: number
  speaker: string
  text: string
}

interface SonioxToken {
  text: string
  is_final?: boolean
  speaker?: string
}

interface SonioxMessage {
  tokens?: SonioxToken[]
  error_code?: string
  error_message?: string
  finished?: boolean
}

function floatTo16BitPCM(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length)
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]))
    output[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return output
}

export function useSonioxTranscription(languageHint = "en") {
  const [status, setStatus] = useState<TranscriptStatus>("idle")
  const [segments, setSegments] = useState<TranscriptSegment[]>([])
  const [interimText, setInterimText] = useState("")
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const mediaStreamRef = useRef<MediaStream | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const segmentsRef = useRef<TranscriptSegment[]>([])
  const currentSpeakerRef = useRef<string | null>(null)
  const forceNewSegmentRef = useRef(true)
  const nextIdRef = useRef(0)

  const cleanupMedia = useCallback(async () => {
    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current.onaudioprocess = null
      processorRef.current = null
    }

    mediaStreamRef.current?.getTracks().forEach((track) => track.stop())
    mediaStreamRef.current = null

    if (audioCtxRef.current) {
      try {
        await audioCtxRef.current.close()
      } catch {
        // already closed
      }
      audioCtxRef.current = null
    }
  }, [])

  const commitFinalToken = useCallback(
    (text: string, speaker: string | undefined) => {
      const speakerKey = speaker || "1"
      const list = segmentsRef.current
      if (
        list.length === 0 ||
        forceNewSegmentRef.current ||
        speakerKey !== currentSpeakerRef.current
      ) {
        segmentsRef.current = [
          ...list,
          { id: nextIdRef.current++, speaker: speakerKey, text: "" },
        ]
        currentSpeakerRef.current = speakerKey
        forceNewSegmentRef.current = false
      }
      const updated = [...segmentsRef.current]
      const last = updated[updated.length - 1]
      updated[updated.length - 1] = { ...last, text: last.text + text }
      segmentsRef.current = updated
      setSegments(updated)
    },
    []
  )

  const handleMessage = useCallback(
    (data: SonioxMessage) => {
      if (data.error_code) {
        setError(`${data.error_code}: ${data.error_message ?? ""}`.trim())
        setStatus("error")
        return
      }
      let interim = ""
      for (const token of data.tokens ?? []) {
        if (token.text === END_TOKEN) {
          forceNewSegmentRef.current = true
          continue
        }
        if (token.is_final) {
          commitFinalToken(token.text, token.speaker)
        } else {
          interim += token.text
        }
      }
      setInterimText(interim)
      if (data.finished) {
        wsRef.current?.close()
      }
    },
    [commitFinalToken]
  )

  const startCapture = useCallback(
    (ws: WebSocket, audioCtx: AudioContext, stream: MediaStream) => {
      const source = audioCtx.createMediaStreamSource(stream)
      const processor = audioCtx.createScriptProcessor(4096, 1, 1)
      const silentGain = audioCtx.createGain()
      silentGain.gain.value = 0

      processor.onaudioprocess = (event) => {
        if (ws.readyState !== WebSocket.OPEN) return
        const input = event.inputBuffer.getChannelData(0)
        ws.send(floatTo16BitPCM(input).buffer as ArrayBuffer)
      }

      source.connect(processor)
      processor.connect(silentGain)
      silentGain.connect(audioCtx.destination)
      processorRef.current = processor
    },
    []
  )

  const reset = useCallback(() => {
    segmentsRef.current = []
    currentSpeakerRef.current = null
    forceNewSegmentRef.current = true
    nextIdRef.current = 0
    setSegments([])
    setInterimText("")
    setError(null)
  }, [])

  const start = useCallback(async () => {
    reset()
    setStatus("connecting")

    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: true,
      })
      mediaStreamRef.current = mediaStream

      const AudioContextCtor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext })
          .webkitAudioContext
      const audioCtx = new AudioContextCtor()
      audioCtxRef.current = audioCtx

      const res = await fetch(`${apiBaseUrl}/api/soniox/temporary-key`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ expires_in_seconds: 60 }),
      })
      const body = await res.json()
      if (!res.ok) {
        throw new Error(body.detail ?? "Failed to get a temporary key.")
      }

      const ws = new WebSocket(SONIOX_WS_URL)
      ws.binaryType = "arraybuffer"
      wsRef.current = ws

      ws.onopen = () => {
        ws.send(
          JSON.stringify({
            api_key: body.api_key,
            model: "stt-rt-v5",
            audio_format: "pcm_s16le",
            sample_rate: audioCtx.sampleRate,
            num_channels: 1,
            language_hints: [languageHint || "en"],
            enable_endpoint_detection: true,
            enable_speaker_diarization: true,
          })
        )
        startCapture(ws, audioCtx, mediaStream)
        setStatus("live")
      }

      ws.onmessage = (event) => {
        handleMessage(JSON.parse(event.data))
      }

      ws.onerror = () => {
        setError("WebSocket connection error.")
        setStatus("error")
      }

      ws.onclose = () => {
        void cleanupMedia()
        setStatus((s) => (s === "error" ? s : "idle"))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setStatus("error")
      await cleanupMedia()
    }
  }, [cleanupMedia, handleMessage, languageHint, reset, startCapture])

  const stop = useCallback(() => {
    setStatus("stopping")
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send("")
    } else if (ws) {
      ws.close()
    } else {
      void cleanupMedia().then(() => setStatus("idle"))
    }
  }, [cleanupMedia])

  return { status, segments, interimText, error, start, stop }
}
