export type SourceStatus = "connected" | "planned" | "needs-key"

export interface TrustedSource {
  id: string
  name: string
  /** Short name for inline "checking…" labels in the transcript. */
  shortName: string
  publisher: string
  covers: string
  url: string
  status: SourceStatus
}

/** Sources claims are checked against. OpenSTAT, the Official Gazette and the DPWH flood control records are wired up. */
export const TRUSTED_SOURCES: TrustedSource[] = [
  {
    id: "psa",
    name: "PSA OpenSTAT",
    shortName: "PSA OpenSTAT",
    publisher: "Philippine Statistics Authority",
    covers: "Employment, prices, population, poverty",
    url: "https://openstat.psa.gov.ph",
    status: "connected",
  },
  {
    id: "flood-control",
    name: "DPWH Flood Control Projects",
    shortName: "DPWH flood control records",
    publisher: "DPWH data, compiled by BetterGov.ph",
    covers:
      "9,855 flood control contracts, 2018–2025: cost, contractor, location",
    url: "https://github.com/bettergovph/bettergov/tree/main/src/data/flood_control",
    status: "connected",
  },
  {
    id: "factcheck",
    name: "Google Fact Check Tools",
    shortName: "Published fact-checks",
    publisher:
      "Published fact-checks (ClaimReview) by independent fact-checkers",
    covers:
      "Claims already reviewed by fact-checkers; used when no data source covers a claim",
    url: "https://toolbox.google.com/factcheck/explorer",
    status: "connected",
  },
  {
    id: "gazette",
    name: "Official Gazette",
    shortName: "Official Gazette",
    publisher: "Presidential Communications Office",
    covers: "Constitution, laws, executive orders",
    url: "https://www.officialgazette.gov.ph",
    status: "connected",
  },
]

export const SOURCES_BY_ID: Record<string, TrustedSource> = Object.fromEntries(
  TRUSTED_SOURCES.map((s) => [s.id, s])
)
