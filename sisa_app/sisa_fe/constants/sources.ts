export type SourceStatus = "connected" | "planned" | "needs-key"

export interface TrustedSource {
  id: string
  name: string
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
    publisher: "Philippine Statistics Authority",
    covers: "Employment, prices, population, poverty",
    url: "https://openstat.psa.gov.ph",
    status: "connected",
  },
  {
    id: "flood-control",
    name: "DPWH Flood Control Projects",
    publisher: "DPWH data, compiled by BetterGov.ph",
    covers:
      "9,855 flood control contracts, 2018–2025: cost, contractor, location",
    url: "https://github.com/bettergovph/bettergov/tree/main/src/data/flood_control",
    status: "connected",
  },
  {
    id: "factcheck",
    name: "Google Fact Check Tools",
    publisher:
      "Published fact-checks (ClaimReview) by independent fact-checkers",
    covers:
      "Claims already reviewed by fact-checkers; used when no data source covers a claim",
    url: "https://toolbox.google.com/factcheck/explorer",
    // Real status comes from GET /api/v1/sources/status (needs FACTCHECK_API_KEY).
    status: "needs-key",
  },
  {
    id: "coa",
    name: "COA Audit Reports",
    publisher: "Commission on Audit",
    covers: "Annual audit reports, notices of disallowance",
    url: "https://www.coa.gov.ph",
    status: "planned",
  },
  {
    id: "dbm",
    name: "DBM Budget Documents",
    publisher: "Department of Budget and Management",
    covers: "GAA, NEP, allotment releases",
    url: "https://www.dbm.gov.ph",
    status: "planned",
  },
  {
    id: "gazette",
    name: "Official Gazette",
    publisher: "Presidential Communications Office",
    covers: "Constitution, laws, executive orders",
    url: "https://www.officialgazette.gov.ph",
    status: "connected",
  },
  {
    id: "sc",
    name: "Supreme Court E-Library",
    publisher: "Supreme Court of the Philippines",
    covers: "Decisions, resolutions, court rules",
    url: "https://elibrary.judiciary.gov.ph",
    status: "planned",
  },
  {
    id: "congress",
    name: "Senate & House Records",
    publisher: "Congress of the Philippines",
    covers: "Bills, committee reports, journals",
    url: "https://web.senate.gov.ph",
    status: "planned",
  },
  {
    id: "bsp",
    name: "BSP Statistics",
    publisher: "Bangko Sentral ng Pilipinas",
    covers: "Inflation, exchange rates, remittances",
    url: "https://www.bsp.gov.ph",
    status: "planned",
  },
]

export const SOURCES_BY_ID: Record<string, TrustedSource> = Object.fromEntries(
  TRUSTED_SOURCES.map((s) => [s.id, s])
)
