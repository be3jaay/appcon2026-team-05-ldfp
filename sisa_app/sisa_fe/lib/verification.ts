import type { Claim, ClaimType } from "@/hooks/use-claim-detection"

/** Response of POST /api/v1/claims/verify (see sisa_api/src/models/verification.py). */
export type VerificationStatus =
  | "SUPPORTED"
  | "CONTRADICTED"
  | "NEEDS_CONTEXT"
  | "INSUFFICIENT_EVIDENCE"
  | "ERROR"

export type AssessmentMethod =
  "OFFICIAL_DATA" | "DOCUMENT_MATCH" | "AI_COMPARISON" | "NONE"

export interface EvidenceItem {
  source: {
    name: string
    publisher: string
    source_type: "OFFICIAL_STATISTICS" | "OFFICIAL_DOCUMENT"
    url: string
    title: string | null
    date: string | null
    document_type: string | null
    document_number: string | null
    dataset: string | null
    table: string | null
  }
  data: {
    relevant_text: string | null
    document_reference: string | null
    value: number | null
    unit: string | null
    period: string | null
    geography: string | null
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
  ERROR: "error",
}

export const VERDICT_META: Record<
  Verdict,
  { label: string; color: string; description: string }
> = {
  factual: {
    label: "Factual",
    color: "#15803D",
    description: "Official sources support this claim.",
  },
  misleading: {
    label: "Misleading",
    color: "#B91C1C",
    description: "Official sources say something different.",
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
      "Checkable, but no official source for this kind of claim is connected yet.",
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
  OFFICIAL_DATA: "Compared with the published official figure.",
  DOCUMENT_MATCH: "Matched against Official Gazette records.",
  AI_COMPARISON:
    "AI compared the claim with the official text shown below. Check the source.",
  NONE: null,
}

/** Claims that go to /verify: the detector found a source that can check them. */
export function isVerifiable(claim: Claim): boolean {
  return claim.check_type === "STATISTICAL" || claim.check_type === "LEGAL"
}

/** "Fact-checks" tab vs "Other statements" tab. */
export function isFactCheck(claim: Claim): boolean {
  return isVerifiable(claim) || claim.type === "fact" || claim.type === "legal"
}

export function verdictOf(
  claim: Claim,
  state: VerifyState | undefined
): Verdict {
  if (!isVerifiable(claim))
    return isFactCheck(claim) ? "no-source" : "not-checkable"
  if (!state || state.state === "checking") return "checking"
  if (state.state === "failed") return "error"
  return STATUS_VERDICT[state.result.assessment.status]
}
