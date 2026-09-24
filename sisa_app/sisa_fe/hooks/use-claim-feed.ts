"use client"

import { useMemo, useState } from "react"

import type { Claim, SegmentClaimStatus } from "@/hooks/use-claim-detection"

const CHECKABLE = new Set(["fact", "legal"])

/**
 * The "current claim" follows the newest detected claim, preferring a
 * checkable one from the latest batch, until the user picks one from history.
 */
export function useClaimFeed(
  claims: Claim[],
  statusById: Record<string, SegmentClaimStatus>
) {
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const latest = useMemo(() => {
    if (claims.length === 0) return null
    const lastSegment = claims[claims.length - 1].segment_id
    const recent = claims.filter((c) => c.segment_id === lastSegment)
    return (
      [...recent].reverse().find((c) => CHECKABLE.has(c.type)) ??
      claims[claims.length - 1]
    )
  }, [claims])

  const selected = selectedId
    ? (claims.find((c) => c.id === selectedId) ?? null)
    : null
  const current = selected ?? latest
  const following = selected === null

  // Newest first, without the claim already shown as current.
  const history = useMemo(
    () => [...claims].reverse().filter((c) => c.id !== current?.id),
    [claims, current]
  )

  const pendingCount = useMemo(
    () =>
      Object.values(statusById).filter(
        (s) => s === "queued" || s === "checking"
      ).length,
    [statusById]
  )

  return {
    current,
    history,
    following,
    pendingCount,
    select: (id: string) => setSelectedId(id),
    followLive: () => setSelectedId(null),
  }
}
