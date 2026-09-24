"use client"

import { useEffect, useRef, useState } from "react"

import { VERDICT_META, type Verdict } from "@/lib/verification"
import { FALLACY_LABELS } from "@/components/claims/rhetoric-badges"
import type { Claim } from "@/hooks/use-claim-detection"

export interface ClaimAlert {
  key: string
  claim: Claim
  label: string
  color: string
}

const HOLD_MS = 9000

/** What is worth interrupting the viewer for, most important first. */
function alertsFor(claim: Claim, verdict: Verdict | undefined): ClaimAlert[] {
  const out: ClaimAlert[] = []
  const add = (kind: string, label: string, color: string) =>
    out.push({ key: `${claim.id}:${kind}`, claim, label, color })
  if (verdict === "misleading")
    add("misleading", "Misleading", VERDICT_META.misleading.color)
  if (claim.contradicts)
    add("conflict", "Conflicts with an earlier claim", "#6D28D9")
  if (verdict === "lacks-context")
    add("lacks-context", "Lacks context", VERDICT_META["lacks-context"].color)
  if (claim.evasion) add("evasion", "Evasive answer", "#9A3412")
  if (claim.fallacy)
    add(
      "fallacy",
      `Fallacy: ${FALLACY_LABELS[claim.fallacy] ?? claim.fallacy}`,
      "#9A3412"
    )
  return out
}

/**
 * The latest new alert (a claim just found misleading, conflicting, evasive…), shown
 * for a few seconds over the video. Each alert is shown once per session.
 */
export function useClaimAlerts(
  claims: Claim[],
  verdicts: Record<string, Verdict>
) {
  const seen = useRef(new Set<string>())
  const [alert, setAlert] = useState<ClaimAlert | null>(null)

  useEffect(() => {
    if (claims.length === 0) {
      seen.current.clear()
      setAlert(null)
      return
    }
    let latest: ClaimAlert | null = null
    for (const claim of claims) {
      const fresh = alertsFor(claim, verdicts[claim.id]).filter(
        (a) => !seen.current.has(a.key)
      )
      fresh.forEach((a) => seen.current.add(a.key))
      // Claims are oldest first: keep the newest claim's most important alert.
      if (fresh.length) latest = fresh[0]
    }
    if (latest) setAlert(latest)
  }, [claims, verdicts])

  useEffect(() => {
    if (!alert) return
    const t = setTimeout(() => setAlert(null), HOLD_MS)
    return () => clearTimeout(t)
  }, [alert])

  return { alert, dismiss: () => setAlert(null) }
}
