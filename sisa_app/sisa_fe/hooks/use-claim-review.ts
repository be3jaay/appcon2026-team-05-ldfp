"use client"

import { useCallback, useEffect, useState } from "react"

import type { Claim } from "@/hooks/use-claim-detection"

/** The reviewer's call on SISA's result. SISA only prepares context; people decide. */
export type ReviewDecision = "confirmed" | "disputed" | "dismissed"

export interface ClaimReview {
  decision: ReviewDecision | null
  note: string
}

export const REVIEW_LABELS: Record<ReviewDecision, string> = {
  confirmed: "Confirmed",
  disputed: "Disputed",
  dismissed: "Dismissed",
}

/** Button labels (the action); REVIEW_LABELS is the resulting state. */
export const REVIEW_ACTIONS: Record<ReviewDecision, string> = {
  confirmed: "Confirm",
  disputed: "Dispute",
  dismissed: "Dismiss",
}

export const REVIEW_HINTS: Record<ReviewDecision, string> = {
  confirmed: "I checked this and agree with the result",
  disputed: "I disagree with the result",
  dismissed: "Not a claim worth checking",
}

const EMPTY: ClaimReview = { decision: null, note: "" }

/** Per-claim review state for this session (kept in memory; export to keep it). */
export function useClaimReview(claims: Claim[]) {
  const [reviews, setReviews] = useState<Record<string, ClaimReview>>({})

  // A new session reuses claim ids: start its reviews fresh.
  const empty = claims.length === 0
  useEffect(() => {
    if (empty) setReviews({})
  }, [empty])

  const setDecision = useCallback((id: string, decision: ReviewDecision) => {
    setReviews((prev) => {
      const current = prev[id] ?? EMPTY
      // Clicking the active decision again clears it.
      const next = current.decision === decision ? null : decision
      return { ...prev, [id]: { ...current, decision: next } }
    })
  }, [])

  const setNote = useCallback((id: string, note: string) => {
    setReviews((prev) => ({ ...prev, [id]: { ...(prev[id] ?? EMPTY), note } }))
  }, [])

  return { reviews, setDecision, setNote }
}

export type ClaimReviews = ReturnType<typeof useClaimReview>
