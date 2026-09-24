"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { apiWsBaseUrl } from "@/lib/api"

const CLAIMS_WS_URL = `${apiWsBaseUrl}/api/v1/claims/ws`

export type ClaimType =
  "fact" | "legal" | "opinion" | "promise" | "sarcasm" | "figurative" | "vague"

/** Which official source can check it (set by the detector). */
export type CheckType = "STATISTICAL" | "LEGAL" | "OTHER"

export interface ClaimEntities {
  metric?: string | null
  value?: number | null
  unit?: string | null
  geography?: string | null
  document_type?: string | null
  document_number?: string | null
  subject?: string | null
  date?: string | null
}

export interface Claim {
  id: string
  segment_id: string
  timestamp: number | null
  speaker: string
  text: string
  quote: string | null
  /** The claim in English (for searching English-language sources). */
  text_en: string | null
  type: ClaimType
  checkworthiness: number
  reason: string
  literal_claim: string | null
  check_type: CheckType
  entities: ClaimEntities | null
  /** Rhetoric flags from the detector (only set when clearly present). */
  fallacy?: string | null
  evasion?: boolean
  rhetoric_note?: string | null
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

/** queued: sent, waiting for a batch/rate-limit slot · checking: LLM call in flight */
export type SegmentClaimStatus =
  "queued" | "checking" | "done" | "skipped" | "error"

type ServerMessage =
  | ({ type: "skipped" } & SkippedSegment)
  | { type: "checking"; segment_ids: string[] }
  | { type: "claims"; segment_ids: string[]; claims: Claim[] }
  | { type: "error"; message: string; fatal?: boolean; segment_ids?: string[] }
  | { type: "done"; claims: number; skipped: number; llm_calls: number }

const PENDING: SegmentClaimStatus[] = ["queued", "checking"]

function withStatus(
  prev: Record<string, SegmentClaimStatus>,
  ids: string[],
  status: SegmentClaimStatus
) {
  const next = { ...prev }
  for (const id of ids) next[id] = status
  return next
}

function failPending(prev: Record<string, SegmentClaimStatus>) {
  const pending = Object.keys(prev).filter((id) => PENDING.includes(prev[id]))
  return pending.length ? withStatus(prev, pending, "error") : prev
}

/**
 * Streams finished transcript segments to the backend claim detector over a
 * websocket and collects the labelled claims it pushes back. Mic and video
 * share this through useSonioxTranscription.
 */
export function useClaimDetection() {
  const [claims, setClaims] = useState<Claim[]>([])
  const [skipped, setSkipped] = useState<SkippedSegment[]>([])
  const [statusById, setStatusById] = useState<
    Record<string, SegmentClaimStatus>
  >({})
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const pendingRef = useRef<string[]>([])

  const send = useCallback((message: object) => {
    const ws = wsRef.current
    const data = JSON.stringify(message)
    if (ws?.readyState === WebSocket.OPEN) ws.send(data)
    else if (ws?.readyState === WebSocket.CONNECTING)
      pendingRef.current.push(data)
    else return false
    return true
  }, [])

  const connect = useCallback(() => {
    wsRef.current?.close()
    pendingRef.current = []
    setClaims([])
    setSkipped([])
    setStatusById({})
    setError(null)

    const ws = new WebSocket(CLAIMS_WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      for (const data of pendingRef.current) ws.send(data)
      pendingRef.current = []
    }

    ws.onmessage = (event) => {
      const message = JSON.parse(event.data) as ServerMessage
      if (message.type === "checking") {
        setStatusById((prev) =>
          withStatus(prev, message.segment_ids, "checking")
        )
      } else if (message.type === "claims") {
        setClaims((prev) => [...prev, ...message.claims])
        setStatusById((prev) => withStatus(prev, message.segment_ids, "done"))
      } else if (message.type === "skipped") {
        const { segment_id, reason } = message
        setSkipped((prev) => [...prev, { segment_id, reason }])
        setStatusById((prev) => withStatus(prev, [segment_id], "skipped"))
      } else if (message.type === "error") {
        setError(message.message)
        if (message.segment_ids) {
          const ids = message.segment_ids
          setStatusById((prev) => withStatus(prev, ids, "error"))
        } else if (message.fatal) {
          setStatusById(failPending)
        }
      }
    }

    ws.onerror = () => setError("Claim detection connection error.")

    ws.onclose = () => {
      if (wsRef.current === ws) wsRef.current = null
      // Anything still waiting will never get an answer on this socket.
      setStatusById(failPending)
    }
  }, [])

  const sendSegment = useCallback(
    (segment: FinalSegment) => {
      if (!segment.text.trim()) return
      if (send({ type: "segment", segment })) {
        setStatusById((prev) =>
          withStatus(prev, [segment.segment_id], "queued")
        )
      }
    },
    [send]
  )

  // Flushes the server-side batch; the server replies "done" and closes.
  const stop = useCallback(() => void send({ type: "stop" }), [send])

  useEffect(() => () => wsRef.current?.close(), [])

  const claimsBySegment = useMemo(() => {
    const grouped: Record<string, Claim[]> = {}
    for (const claim of claims) {
      ;(grouped[claim.segment_id] ??= []).push(claim)
    }
    return grouped
  }, [claims])

  return {
    claims,
    claimsBySegment,
    statusById,
    skipped,
    error,
    connect,
    sendSegment,
    stop,
  }
}
