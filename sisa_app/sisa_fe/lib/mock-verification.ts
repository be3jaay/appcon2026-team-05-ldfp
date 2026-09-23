/**
 * MOCK verification, until the backend verifies claims. It picks the trusted
 * sources a claim would be checked against and shows the query it would run.
 * It never invents findings: every checkable claim stays "pending".
 */
import type { Claim } from "@/hooks/use-claim-detection"
import { SOURCES_BY_ID, type TrustedSource } from "@/constants/sources"

export type Verdict = "pending" | "not-checkable"

export interface EvidenceItem {
  source: TrustedSource
  query: string
  note: string
}

export interface Verification {
  verdict: Verdict
  summary: string
  evidence: EvidenceItem[]
}

const SOURCE_RULES: { id: string; pattern: RegExp }[] = [
  { id: "coa", pattern: /\b(coa|audit|disallow\w*|liquidat\w*)/i },
  {
    id: "dbm",
    pattern:
      /(₱|\b(dbm|budget|badyet|pondo|funds?|gaa|pesos?|piso|milyon\w*|bilyon\w*|million|billion))/i,
  },
  {
    id: "psa",
    pattern:
      /(%|\b(psa|unemploy\w*|inflation|percent|porsyento|poverty|population|rate))/i,
  },
  {
    id: "gazette",
    pattern:
      /\b(batas|laws?|republic act|executive order|konstitusyon|constitution|article|section)/i,
  },
  {
    id: "sc",
    pattern:
      /\b(korte|court|supreme|ruling|desisyon|decision|impeach\w*|trial)/i,
  },
  {
    id: "congress",
    pattern: /\b(senado|senate|kamara|congress|house|bill|panukala|hearing)/i,
  },
  { id: "bsp", pattern: /\b(bsp|exchange rate|interest rate|remittance\w*)/i },
]

const NOT_CHECKABLE: Record<string, string> = {
  opinion: "Opinion: a value judgment, so there is nothing to verify.",
  promise: "Promise about the future: can be tracked, not verified yet.",
  vague: "Too vague to verify: it's missing who, how much, or when.",
}

function checkableText(claim: Claim): string | null {
  if (claim.type === "fact" || claim.type === "legal") return claim.text
  if (claim.type === "figurative" || claim.type === "sarcasm")
    return claim.literal_claim
  return null
}

export function mockVerify(claim: Claim): Verification {
  const text = checkableText(claim)
  if (!text) {
    return {
      verdict: "not-checkable",
      summary:
        NOT_CHECKABLE[claim.type] ??
        "No checkable claim inside this figure of speech.",
      evidence: [],
    }
  }

  const ids = SOURCE_RULES.filter((r) => r.pattern.test(text)).map((r) => r.id)
  if (ids.length === 0) ids.push(claim.type === "legal" ? "gazette" : "psa")

  const query = text.length > 90 ? `${text.slice(0, 87)}…` : text
  return {
    verdict: "pending",
    summary:
      "Not verified yet. These are the sources it would be checked against.",
    evidence: ids.slice(0, 3).map((id) => ({
      source: SOURCES_BY_ID[id],
      query,
      note:
        SOURCES_BY_ID[id].status === "connected"
          ? "Source connected. The matched record will show here."
          : "Demo evidence: the matched passage will show here once this source is connected.",
    })),
  }
}
