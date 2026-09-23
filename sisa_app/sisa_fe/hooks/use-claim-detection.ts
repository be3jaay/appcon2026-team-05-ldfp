"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { apiWsBaseUrl } from "@/lib/api"

const CLAIMS_WS_URL = `${apiWsBaseUrl}/api/v1/claims/ws`

export type ClaimType =
  "fact" | "legal" | "opinion" | "promise" | "sarcasm" | "figurative" | "vague"

export interface Claim {
  id: string
  segment_id: string
  timestamp: number | null
  speaker: string
  text: string
  type: ClaimType
  checkworthiness: number
  reason: string
  literal_claim: string | null
}

export interface SkippedSegment {
  segment_id: string
  reason: string
}

export interface FinalSegment {
  segment_id: string
  text: string
  speaker: string
  start_ms?: number
  end_ms?: number
}

type ServerMessage =
  | ({ type: "skipped" } & SkippedSegment)
  | { type: "claims"; segment_ids: string[]; claims: Claim[] }
  | { type: "error"; message: string; fatal?: boolean }
  | { type: "done"; claims: number; skipped: number; llm_calls: number }

/**
 * Streams finished transcript segments to the backend claim detector over a
 * websocket and collects the labelled claims it pushes back. Mic and video
 * share this through useSonioxTranscription.
 */
export function useClaimDetection() {
  const [claims, setClaims] = useState<Claim[]>([])
  const [skipped, setSkipped] = useState<SkippedSegment[]>([])
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const pendingRef = useRef<string[]>([])

  const send = useCallback((message: object) => {
    const ws = wsRef.current
    const data = JSON.stringify(message)
    if (ws?.readyState === WebSocket.OPEN) ws.send(data)
    else if (ws?.readyState === WebSocket.CONNECTING)
      pendingRef.current.push(data)
  }, [])

  const connect = useCallback(() => {
    wsRef.current?.close()
    pendingRef.current = []
    setClaims([])
    setSkipped([])
    setError(null)

    const ws = new WebSocket(CLAIMS_WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      for (const data of pendingRef.current) ws.send(data)
      pendingRef.current = []
    }

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data) as ServerMessage
      if (message.type === "claims") {
        setClaims((prev) => [...prev, ...message.claims])
      } else if (message.type === "skipped") {
        const { segment_id, reason } = message
        setSkipped((prev) => [...prev, { segment_id, reason }])
      } else if (message.type === "error") {
        setError(message.message)
      }
    }

    ws.onerror = () => setError("Claim detection connection error.")

    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null
    }
  }, [])

  const sendSegment = useCallback(
    (segment: FinalSegment) => {
      if (!segment.text.trim()) return
      send({ type: "segment", segment })
    },
    [send]
  )

  // Flushes the server-side batch; the server replies "done" and closes.
  const stop = useCallback(() => send({ type: "stop" }), [send])

  useEffect(() => () => wsRef.current?.close(), [])

  return { claims, skipped, error, connect, sendSegment, stop }
}
