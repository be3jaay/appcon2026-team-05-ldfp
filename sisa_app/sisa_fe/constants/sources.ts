export type SourceStatus = "connected" | "planned"

export interface TrustedSource {
  id: string
  name: string
  publisher: string
  covers: string
  url: string
  status: SourceStatus
}

/** Official sources claims are checked against. OpenSTAT and the Official Gazette are wired up. */
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
