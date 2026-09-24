import { formatTime } from "@/lib/video"
import { VERDICT_META, verdictOf, type VerifyState } from "@/lib/verification"
import { CLAIM_LABELS } from "@/components/claims/claim-text"
import { FALLACY_LABELS } from "@/components/claims/rhetoric-badges"
import type { Claim } from "@/hooks/use-claim-detection"
import { REVIEW_LABELS, type ClaimReview } from "@/hooks/use-claim-review"
import type { TranscriptSegment } from "@/hooks/use-soniox-transcription"

export interface SessionExport {
  segments: TranscriptSegment[]
  claims: Claim[]
  verifications: Record<string, VerifyState>
  reviews: Record<string, ClaimReview>
}

function claimTime(claim: Claim) {
  return claim.timestamp !== null ? formatTime(claim.timestamp / 1000) : null
}

function flags(claim: Claim, byId: Map<string, Claim>) {
  const out: string[] = []
  if (claim.evasion) out.push("Evasive answer")
  if (claim.fallacy)
    out.push(`Fallacy: ${FALLACY_LABELS[claim.fallacy] ?? claim.fallacy}`)
  if (claim.contradicts) {
    const earlier = byId.get(claim.contradicts)
    out.push(
      `Conflicts with an earlier claim${earlier ? ` (“${earlier.text}”)` : ""}`
    )
  }
  return out
}

/** A readable report: every claim with its verdict, evidence and the reviewer's call, then the transcript. */
export function sessionMarkdown({
  segments,
  claims,
  verifications,
  reviews,
}: SessionExport) {
  const byId = new Map(claims.map((c) => [c.id, c]))
  const lines = [
    "# SISA session report",
    "",
    `Exported ${new Date().toLocaleString()} · ${claims.length} statements detected · ${segments.length} transcript lines`,
    "",
    "SISA prepares context; the verdicts below are machine-assisted and need human review.",
    "",
    "## Claims",
    "",
  ]
  claims.forEach((claim, i) => {
    const state = verifications[claim.id]
    const verdict = verdictOf(claim, state)
    const result = state?.state === "done" ? state.result : null
    const review = reviews[claim.id]
    const when = claimTime(claim)
    lines.push(
      `### ${i + 1}. ${claim.text}`,
      "",
      `- **Speaker** ${claim.speaker}${when ? ` at ${when}` : ""} · ${CLAIM_LABELS[claim.type]}`,
      `- **SISA result:** ${VERDICT_META[verdict].label}${result ? ` — ${result.assessment.explanation}` : ""}`
    )
    if (claim.quote) lines.push(`- **Quote:** “${claim.quote}”`)
    const f = flags(claim, byId)
    if (f.length) {
      lines.push(`- **Flags:** ${f.join("; ")}`)
      if (claim.rhetoric_note) lines.push(`  - ${claim.rhetoric_note}`)
      if (claim.contradiction_note)
        lines.push(`  - ${claim.contradiction_note}`)
    }
    for (const item of result?.evidence ?? []) {
      lines.push(
        `- **Evidence:** [${item.source.title ?? item.source.name}](${item.source.url}) (${item.source.name}${item.data.rating ? `, rated “${item.data.rating}”` : ""})`
      )
    }
    lines.push(
      `- **Reviewer:** ${review?.decision ? REVIEW_LABELS[review.decision] : "Not reviewed"}${review?.note ? ` — ${review.note}` : ""}`,
      ""
    )
  })
  lines.push("## Transcript", "")
  for (const seg of segments) {
    const when =
      seg.startTime !== undefined ? `[${formatTime(seg.startTime)}] ` : ""
    lines.push(`${when}**Speaker ${seg.speaker}:** ${seg.text}`, "")
  }
  return lines.join("\n")
}

/** Everything as data, for other tools. */
export function sessionJson({
  segments,
  claims,
  verifications,
  reviews,
}: SessionExport) {
  return JSON.stringify(
    {
      exported_at: new Date().toISOString(),
      transcript: segments,
      claims: claims.map((claim) => {
        const state = verifications[claim.id]
        return {
          ...claim,
          verdict: verdictOf(claim, state),
          verification: state?.state === "done" ? state.result : null,
          review: reviews[claim.id] ?? null,
        }
      }),
    },
    null,
    2
  )
}

export function downloadFile(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }))
  const a = document.createElement("a")
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function exportName(ext: string) {
  const d = new Date()
  const pad = (n: number) => String(n).padStart(2, "0")
  return `sisa-session-${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}.${ext}`
}
