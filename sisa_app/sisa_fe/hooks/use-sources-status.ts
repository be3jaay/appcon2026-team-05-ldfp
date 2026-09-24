"use client"

import { useEffect, useState } from "react"

import { apiBaseUrl } from "@/lib/api"

export interface SourcesStatus {
  factcheck: boolean
  web_search?: boolean
  llm: boolean
}

/** Which optional sources the backend can use right now (API keys present). */
export function useSourcesStatus() {
  const [status, setStatus] = useState<SourcesStatus | null>(null)
  useEffect(() => {
    let cancelled = false
    fetch(`${apiBaseUrl}/api/v1/sources/status`)
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => !cancelled && body && setStatus(body))
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])
  return status
}
