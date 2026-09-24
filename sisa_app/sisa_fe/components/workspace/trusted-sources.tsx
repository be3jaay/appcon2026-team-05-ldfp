"use client"

import { ArrowUpRight, ShieldCheck } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  TRUSTED_SOURCES,
  type SourceStatus,
  type TrustedSource,
} from "@/constants/sources"
import { useSourcesStatus } from "@/hooks/use-sources-status"
import { InfoPopover } from "@/components/workspace/popover"

const STATUS_LABEL: Record<SourceStatus, string> = {
  connected: "Connected",
  planned: "Planned",
  "needs-key": "Needs API key",
}

function SourceRow({ source }: { source: TrustedSource }) {
  const connected = source.status === "connected"
  return (
    <li className="flex items-start gap-3 border-b border-line px-4 py-2.5 last:border-b-0">
      <ShieldCheck
        className={cn(
          "mt-0.5 h-4 w-4 shrink-0",
          connected ? "text-brand-accent" : "text-ink-faint"
        )}
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <a
            href={source.url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-0.5 text-[13px] font-semibold text-ink hover:text-brand-accent"
          >
            {source.name}
            <ArrowUpRight className="h-3 w-3" />
          </a>
          <span
            className={cn(
              "rounded-full px-1.5 text-[9px] leading-4 font-semibold tracking-[0.06em] uppercase",
              connected
                ? "bg-brand-accent/10 text-brand-accent"
                : "bg-canvas text-ink-faint"
            )}
          >
            {STATUS_LABEL[source.status]}
          </span>
        </div>
        <p className="m-0 text-[11px] leading-snug text-ink-faint">
          {source.publisher} · {source.covers}
        </p>
      </div>
    </li>
  )
}

function useSources() {
  const live = useSourcesStatus()
  // Sources that depend on a server-side API key show their live status.
  const keyed: Record<string, boolean | undefined> = {
    factcheck: live?.factcheck,
    "web-search": live?.web_search,
  }
  return TRUSTED_SOURCES.map((s) =>
    live && s.id in keyed
      ? {
          ...s,
          status: (keyed[s.id] ? "connected" : "needs-key") as SourceStatus,
        }
      : s
  )
}

/** Header button: the sources claims are checked against, with their status. */
export function SourcesButton() {
  const sources = useSources()
  const connected = sources.filter((s) => s.status === "connected").length
  return (
    <InfoPopover
      label="Trusted data sources"
      title={`Trusted data sources · ${connected}/${sources.length} connected`}
      className="w-[360px]"
      triggerClassName="flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-medium text-white/90 transition-colors hover:bg-white/20"
      trigger={
        <>
          <ShieldCheck className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Sources</span>
          <span className="font-mono text-[10px] text-white/70">
            {connected}/{sources.length}
          </span>
        </>
      }
    >
      <ul className="m-0 max-h-[60svh] list-none overflow-y-auto p-0">
        {sources.map((s) => (
          <SourceRow key={s.id} source={s} />
        ))}
      </ul>
    </InfoPopover>
  )
}
