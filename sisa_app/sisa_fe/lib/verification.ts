import { SOURCES_BY_ID } from "@/constants/sources"
import type { Claim, ClaimType } from "@/hooks/use-claim-detection"

/** Response of POST /api/v1/claims/verify (see sisa_api/src/models/verification.py). */
export type VerificationStatus =
  | "SUPPORTED"
  | "CONTRADICTED"
  | "NEEDS_CONTEXT"
  | "INSUFFICIENT_EVIDENCE"
  | "NO_SOURCE"
  | "ERROR"

export type AssessmentMethod =
  | "OFFICIAL_DATA"
  | "DOCUMENT_MATCH"
  | "AI_COMPARISON"
  | "PUBLISHED_FACT_CHECK"
  | "AI_WEB_SEARCH"
  | "NONE"

export interface EvidenceItem {
  source: {
    name: string
    publisher: string
    source_type:
      | "OFFICIAL_STATISTICS"
      | "OFFICIAL_DOCUMENT"
      | "GOVERNMENT_DATASET"
      | "PUBLISHED_FACT_CHECK"
      | "WEB_SEARCH_RESULT"
    url: string
    title: string | null
    date: string | null
    document_type: string | null
    document_number: string | null
    dataset: string | null
    table: string | null
    /** Web search results only: how strong the source is. */
    reliability?:
      "government" | "fact_checker" | "news" | "reference" | "other" | null
  }
  data: {
    relevant_text: string | null
    document_reference: string | null
    value: number | null
    unit: string | null
    period: string | null
    geography: string | null
    /** A fact-checker's own rating, verbatim. */
    rating: string | null
    claimant: string | null
  }
  relevance: "DIRECT" | "RELATED"
}

export interface VerificationResult {
  claim: { text: string; type: "STATISTICAL" | "LEGAL_ISSUANCE" | "OTHER" }
  assessment: {
    status: VerificationStatus
    explanation: string
    method: AssessmentMethod
  }
  evidence: EvidenceItem[]
}

export type VerifyState =
  | { state: "checking" }
  | { state: "done"; result: VerificationResult }
  | { state: "failed"; message: string }

/** What the UI shows for a claim. */
export type Verdict =
  | "factual"
  | "misleading"
  | "lacks-context"
  | "no-evidence"
  | "checking"
  | "error"
  | "no-source"
  | "not-checkable"

const STATUS_VERDICT: Record<VerificationStatus, Verdict> = {
  SUPPORTED: "factual",
  CONTRADICTED: "misleading",
  NEEDS_CONTEXT: "lacks-context",
  INSUFFICIENT_EVIDENCE: "no-evidence",
  NO_SOURCE: "no-source",
  ERROR: "error",
}

export const VERDICT_META: Record<
  Verdict,
  { label: string; color: string; description: string }
> = {
  factual: {
    label: "Factual",
    color: "#15803D",
    description: "Official data or a published fact-check supports this claim.",
  },
  misleading: {
    label: "Misleading",
    color: "#B91C1C",
    description: "Official data or a published fact-check says otherwise.",
  },
  "lacks-context": {
    label: "Lacks context",
    color: "#B45309",
    description:
      "An official source was found, but it doesn't settle the claim on its own.",
  },
  "no-evidence": {
    label: "No evidence",
    color: "#5B6B7F",
    description:
      "No matching official record was found. That alone doesn't make it false.",
  },
  checking: {
    label: "Checking…",
    color: "#007EA7",
    description: "Looking this up in official sources.",
  },
  error: {
    label: "Couldn't check",
    color: "#5B6B7F",
    description: "An official source couldn't be reached. Try again later.",
  },
  "no-source": {
    label: "No source yet",
    color: "#8A97A8",
    description:
      "Not checked: none of SISA's sources cover this kind of claim yet.",
  },
  "not-checkable": {
    label: "Not checkable",
    color: "#8A97A8",
    description: "Not a statement of fact.",
  },
}

/** Why a statement isn't fact-checked, per detected type. */
export const STATEMENT_KIND: Partial<Record<ClaimType, string>> = {
  opinion: "An opinion or value judgment. There's nothing to look up.",
  promise:
    "A promise about the future. It can be tracked later, not verified now.",
  vague:
    "Sounds factual but is missing details (who, how much, when) needed to check it.",
  sarcasm:
    "Sarcasm: the words mean the opposite of what's said. See the literal claim, if any.",
  figurative: "A figure of speech. See the literal claim inside it, if any.",
}

export const METHOD_NOTE: Record<AssessmentMethod, string | null> = {
  OFFICIAL_DATA: "Compared with the published official figure or records.",
  DOCUMENT_MATCH: "Matched against Official Gazette records.",
  AI_COMPARISON:
    "AI compared the claim with the official text shown below. Check the source.",
  AI_WEB_SEARCH:
    "AI searched the web and judged the claim from the pages below. Weaker than official data: check the sources.",
  PUBLISHED_FACT_CHECK:
    "Based on an independent fact-checker's published rating of the same claim (their verdict, not SISA's data).",
  NONE: null,
}

/**
 * Claims sent to /verify: anything the detector routed to a data source, plus every
 * fact/legal claim (the backend falls back to published fact-checks, or says
 * "no source").
 */
export function isVerifiable(claim: Claim): boolean {
  return (
    claim.check_type === "STATISTICAL" ||
    claim.check_type === "LEGAL" ||
    claim.type === "fact" ||
    claim.type === "legal"
  )
}

/** "Fact-checks" tab vs "Other statements" tab. */
export function isFactCheck(claim: Claim): boolean {
  return isVerifiable(claim)
}

// Same words the backend uses to route a statistical claim to the DPWH records.
const FLOOD_CONTROL = /flood|baha|dike|revetment|drainage|slope protection/i

function sourceName(id: string, fallback: string): string {
  return SOURCES_BY_ID[id]?.shortName ?? fallback
}

/**
 * The sources the backend will consult for this claim, in order (see
 * claim_verification_service.verify). Used to name them while a check runs.
 */
export function checkingSources(claim: Claim): string[] {
  const factChecks = sourceName("factcheck", "published fact-checks")
  if (claim.check_type === "STATISTICAL") {
    const subject = `${claim.entities?.metric ?? ""} ${claim.text}`
    return [
      FLOOD_CONTROL.test(subject)
        ? sourceName("flood-control", "DPWH flood control records")
        : sourceName("psa", "PSA OpenSTAT"),
      factChecks,
    ]
  }
  if (claim.check_type === "LEGAL") {
    return [sourceName("gazette", "Official Gazette"), factChecks]
  }
  return [factChecks]
}

export const RELIABILITY_LABEL: Record<string, string> = {
  government: "Government",
  fact_checker: "Fact-checker",
  news: "News",
  reference: "Reference",
  other: "Other website",
}

/** Verdict implied by a fact-checker's own rating words (for colouring the rating chip). */
export function ratingVerdict(rating: string | null): Verdict | null {
  if (!rating) return null
  const r = rating.toLowerCase()
  if (
    /missing context|needs context|half[ -]true|unproven|unverified|kulang sa konteksto/.test(
      r
    )
  )
    return "lacks-context"
  if (
    /false|fake|hoax|mislead|incorrect|inaccurate|fabricat|distort|exaggerat|not true|untrue|\bmali\b|hindi totoo|peke/.test(
      r
    )
  )
    return "misleading"
  if (/\btrue\b|\baccurate\b|\bcorrect\b|\btotoo\b|\btama\b/.test(r))
    return "factual"
  return null
}

export function verdictOf(
  claim: Claim,
  state: VerifyState | undefined
): Verdict {
  if (!isVerifiable(claim)) return "not-checkable"
  if (!state || state.state === "checking") return "checking"
  if (state.state === "failed") return "error"
  return STATUS_VERDICT[state.result.assessment.status]
}
