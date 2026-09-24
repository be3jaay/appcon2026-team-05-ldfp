"use client"

import { useEffect, useRef, useState } from "react"

import type { Claim, SegmentClaimStatus } from "@/hooks/use-claim-detection"
import type {
  TranscriptSegment,
  TranscriptStatus,
} from "@/hooks/use-soniox-transcription"
import { apiBaseUrl } from "@/lib/api"
import {
  isVerifiable,
  type VerificationResult,
  type VerifyState,
} from "@/lib/verification"

const SUMMARY_URL = `${apiBaseUrl}/api/v1/session-summary`

export interface SessionSummary {
  language: "tl"
  summary_text: string
  audio_base64: string | null
  audio_format: string
  audio_content_type: string
  audio_error: string | null
}

export type SessionSummaryState =
  | { state: "idle" }
  | { state: "waiting" }
  | { state: "generating" }
  | { state: "done"; result: SessionSummary }
  | { state: "failed"; message: string }

interface SessionSummaryInput {
  status: TranscriptStatus
  segments: TranscriptSegment[]
  claims: Claim[]
  claimStatus: Record<string, SegmentClaimStatus>
  verifications: Record<string, VerifyState>
}

function settledClaimStatus(status: SegmentClaimStatus | undefined) {
  return status === "done" || status === "skipped" || status === "error"
}

function verificationResults(
  claims: Claim[],
  verifications: Record<string, VerifyState>
): VerificationResult[] {
  return claims.flatMap((claim) => {
    const state = verifications[claim.id]
    return state?.state === "done" ? [state.result] : []
  })
}

/**
 * After Stop / End is clicked, waits for claim detection and verification to
 * finish, then requests one Tagalog summary for the completed session.
 */
export function useSessionSummary({
  status,
  segments,
  claims,
  claimStatus,
  verifications,
}: SessionSummaryInput): SessionSummaryState {
  const [summary, setSummary] = useState<SessionSummaryState>({
    state: "idle",
  })
  const shouldGenerateRef = useRef(false)
  const requestRef = useRef<AbortController | null>(null)

  useEffect(() => {
    if (status === "connecting" || status === "live") {
      shouldGenerateRef.current = true
      requestRef.current?.abort()
      requestRef.current = null
      setSummary({ state: "idle" })
    }
  }, [status])

  useEffect(() => {
    if (!shouldGenerateRef.current || status !== "idle") return

    const finishedSegments = segments.filter((segment) => segment.text.trim())
    if (finishedSegments.length === 0) return

    const claimsSettled = finishedSegments.every((segment) =>
      settledClaimStatus(claimStatus[String(segment.id)])
    )
    const verificationsSettled = claims.filter(isVerifiable).every((claim) => {
      const state = verifications[claim.id]
      return state?.state === "done" || state?.state === "failed"
    })

    if (!claimsSettled || !verificationsSettled) {
      setSummary({ state: "waiting" })
      return
    }

    shouldGenerateRef.current = false
    const controller = new AbortController()
    requestRef.current = controller
    setSummary({ state: "generating" })

    void (async () => {
      try {
        const response = await fetch(SUMMARY_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            transcript: finishedSegments.map((segment) => ({
              segment_id: String(segment.id),
              text: segment.text,
              speaker: segment.speaker,
              start_ms: segment.startMs ?? null,
              end_ms: segment.endMs ?? null,
            })),
            claims,
            evidence: verificationResults(claims, verifications),
          }),
        })
        const body = await response.json().catch(() => null)
        if (!response.ok) {
          throw new Error(
            body?.detail?.toString() ??
              `Session summary failed (${response.status})`
          )
        }
        setSummary({ state: "done", result: body as SessionSummary })
      } catch (error) {
        if (controller.signal.aborted) return
        setSummary({
          state: "failed",
          message: error instanceof Error ? error.message : String(error),
        })
      } finally {
        if (requestRef.current === controller) requestRef.current = null
      }
    })()
  }, [claimStatus, claims, segments, status, verifications])

  useEffect(
    () => () => {
      requestRef.current?.abort()
    },
    []
  )

  return summary
}
