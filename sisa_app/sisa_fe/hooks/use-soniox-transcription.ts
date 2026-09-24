"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { useClaimDetection } from "@/hooks/use-claim-detection"
import { apiBaseUrl } from "@/lib/api"
import {
  micInput,
  type AudioInput,
  type AudioInputFactory,
} from "@/lib/audio-inputs"

const SONIOX_WS_URL = "wss://stt-rt.soniox.com/transcribe-websocket"
const END_TOKEN = "<end>"

export type TranscriptStatus =
  "idle" | "connecting" | "live" | "stopping" | "error"

export interface TranscriptSegment {
  id: number
  speaker: string
  text: string
  startTime?: number
  startMs?: number
  endMs?: number
}

interface SonioxToken {
  text: string
  is_final?: boolean
  speaker?: string
  start_ms?: number
  end_ms?: number
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

// Philippine speech switches between Tagalog and English mid-sentence (Taglish): hint both.
const DEFAULT_LANGUAGE_HINTS = ["tl", "en"]

export function useSonioxTranscription(
  languageHints: string[] = DEFAULT_LANGUAGE_HINTS
) {
  const [status, setStatus] = useState<TranscriptStatus>("idle")
  const [segments, setSegments] = useState<TranscriptSegment[]>([])
  const [interimText, setInterimText] = useState("")
  const [error, setError] = useState<string | null>(null)
  const claimDetection = useClaimDetection()
  const {
    sendSegment,
    stop: stopClaims,
    connect: connectClaims,
  } = claimDetection

  const wsRef = useRef<WebSocket | null>(null)
  const inputRef = useRef<AudioInput | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const segmentsRef = useRef<TranscriptSegment[]>([])
  const currentSpeakerRef = useRef<string | null>(null)
  const forceNewSegmentRef = useRef(true)
  const nextIdRef = useRef(0)
  const sentIdRef = useRef(-1)
  const stopRef = useRef<() => void>(() => {})

  const cleanupMedia = useCallback(async () => {
    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current.onaudioprocess = null
      processorRef.current = null
    }

    const input = inputRef.current
    inputRef.current = null
    await input?.release()
  }, [])

  // A segment is final once Soniox ends the utterance (<end>), the speaker
  // changes, or the stream stops. Each one is sent to claim detection once.
  const finalizeLastSegment = useCallback(() => {
    const last = segmentsRef.current[segmentsRef.current.length - 1]
    if (!last || last.id <= sentIdRef.current) return
    sentIdRef.current = last.id
    sendSegment({
      segment_id: String(last.id),
      text: last.text.trim(),
      speaker: last.speaker,
      start_ms: last.startMs,
      end_ms: last.endMs,
    })
  }, [sendSegment])

  const commitFinalToken = useCallback(
    (token: SonioxToken) => {
      const speakerKey = token.speaker || "1"
      const list = segmentsRef.current
      if (
        list.length === 0 ||
        forceNewSegmentRef.current ||
        speakerKey !== currentSpeakerRef.current
      ) {
        finalizeLastSegment()
        segmentsRef.current = [
          ...list,
          {
            id: nextIdRef.current++,
            speaker: speakerKey,
            text: "",
            startTime: inputRef.current?.now?.(),
            startMs: token.start_ms,
          },
        ]
        currentSpeakerRef.current = speakerKey
        forceNewSegmentRef.current = false
      }
      const updated = [...segmentsRef.current]
      const last = updated[updated.length - 1]
      updated[updated.length - 1] = {
        ...last,
        text: last.text + token.text,
        endMs: token.end_ms ?? last.endMs,
      }
      segmentsRef.current = updated
      setSegments(updated)
    },
    [finalizeLastSegment]
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
          finalizeLastSegment()
          continue
        }
        if (token.is_final) {
          commitFinalToken(token)
        } else {
          interim += token.text
        }
      }
      setInterimText(interim)
      if (data.finished) {
        wsRef.current?.close()
      }
    },
    [commitFinalToken, finalizeLastSegment]
  )

  const startCapture = useCallback((ws: WebSocket, input: AudioInput) => {
    const { context: audioCtx, node: source } = input
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
  }, [])

  const reset = useCallback(() => {
    segmentsRef.current = []
    currentSpeakerRef.current = null
    forceNewSegmentRef.current = true
    nextIdRef.current = 0
    sentIdRef.current = -1
    setSegments([])
    setInterimText("")
    setError(null)
  }, [])

  const start = useCallback(
    async (inputFactory: AudioInputFactory = micInput) => {
      reset()
      setStatus("connecting")

      try {
        const input = await inputFactory()
        inputRef.current = input
        const audioCtx = input.context

        const res = await fetch(`${apiBaseUrl}/api/soniox/temporary-key`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expires_in_seconds: 60 }),
        })
        const body = await res.json()
        if (!res.ok) {
          throw new Error(body.detail ?? "Failed to get a temporary key.")
        }

        connectClaims()
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
              language_hints: languageHints,
              enable_endpoint_detection: true,
              enable_speaker_diarization: true,
            })
          )
          startCapture(ws, input)
          input.onEnded?.(() => stopRef.current())
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
          if (wsRef.current === ws) wsRef.current = null
          finalizeLastSegment()
          stopClaims()
          void cleanupMedia()
          setStatus((s) => (s === "error" ? s : "idle"))
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err))
        setStatus("error")
        await cleanupMedia()
      }
    },
    [
      cleanupMedia,
      connectClaims,
      finalizeLastSegment,
      handleMessage,
      languageHints,
      reset,
      startCapture,
      stopClaims,
    ]
  )

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

  useEffect(() => {
    stopRef.current = stop
  }, [stop])

  useEffect(
    () => () => {
      wsRef.current?.close()
      void cleanupMedia()
    },
    [cleanupMedia]
  )

  return {
    status,
    segments,
    interimText,
    error,
    start,
    stop,
    claims: claimDetection.claims,
    claimsBySegment: claimDetection.claimsBySegment,
    claimStatus: claimDetection.statusById,
    skippedSegments: claimDetection.skipped,
    claimsError: claimDetection.error,
  }
}
