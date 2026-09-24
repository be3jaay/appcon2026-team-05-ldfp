"use client"

import { useEffect, useRef, useState } from "react"

import { apiBaseUrl } from "@/lib/api"
import {
  isVerifiable,
  type VerificationResult,
  type VerifyState,
} from "@/lib/verification"
import type { Claim } from "@/hooks/use-claim-detection"

const VERIFY_URL = `${apiBaseUrl}/api/v1/claims/verify`
const MAX_CLAIM_LENGTH = 500

async function verify(claim: Claim): Promise<VerificationResult> {
  const res = await fetch(VERIFY_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      claim: claim.text.slice(0, MAX_CLAIM_LENGTH),
      claim_type: claim.check_type,
      entities: claim.entities ?? {},
    }),
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(
      body?.detail?.toString() ?? `Verification failed (${res.status})`
    )
  }
  return res.json()
}

/**
 * Verifies every checkable claim against official sources, one request at a
 * time (the backend paces its own LLM and source calls). Results are keyed
 * by claim id and reset when a new session starts.
 */
export function useClaimVerification(claims: Claim[]) {
  const [byId, setById] = useState<Record<string, VerifyState>>({})
  const queuedRef = useRef<Set<string>>(new Set())
  // Each queued claim remembers its session, because claim ids restart per session.
  const queueRef = useRef<{ claim: Claim; session: number }[]>([])
  const runningRef = useRef(false)
  const sessionRef = useRef(0)

  useEffect(() => {
    if (claims.length === 0) {
      if (queuedRef.current.size === 0) return
      // New session: forget previous results and drop anything still queued.
      sessionRef.current += 1
      queuedRef.current = new Set()
      queueRef.current = []
      setById({})
      return
    }

    const fresh = claims.filter(
      (c) => isVerifiable(c) && !queuedRef.current.has(c.id)
    )
    if (fresh.length === 0) return
    for (const c of fresh) queuedRef.current.add(c.id)
    queueRef.current.push(
      ...fresh.map((claim) => ({ claim, session: sessionRef.current }))
    )
    setById((prev) => {
      const next = { ...prev }
      for (const c of fresh) next[c.id] = { state: "checking" }
      return next
    })

    if (runningRef.current) return
    runningRef.current = true
    void (async () => {
      while (queueRef.current.length) {
        const { claim, session } = queueRef.current.shift()!
        let outcome: VerifyState
        try {
          outcome = { state: "done", result: await verify(claim) }
        } catch (err) {
          outcome = {
            state: "failed",
            message: err instanceof Error ? err.message : String(err),
          }
        }
        if (session === sessionRef.current) {
          setById((prev) => ({ ...prev, [claim.id]: outcome }))
        }
      }
      runningRef.current = false
    })()
  }, [claims])

  return byId
}
