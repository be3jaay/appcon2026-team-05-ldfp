"use client"

import { ArrowUpRight, ShieldCheck } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  TRUSTED_SOURCES,
  type SourceStatus,
  type TrustedSource,
} from "@/constants/sources"
import { useSourcesStatus } from "@/hooks/use-sources-status"
import { Panel, PanelHeader } from "@/components/workspace/panel"

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

export function TrustedSources({
  collapsible = false,
  className,
}: {
  collapsible?: boolean
  className?: string
}) {
  const live = useSourcesStatus()
  // Sources that depend on a server-side API key show their live status.
  const keyed: Record<string, boolean | undefined> = {
    factcheck: live?.factcheck,
    "web-search": live?.web_search,
  }
  const sources = TRUSTED_SOURCES.map((s) =>
    live && s.id in keyed
      ? {
          ...s,
          status: (keyed[s.id] ? "connected" : "needs-key") as SourceStatus,
        }
      : s
  )
  const list = (
    <ul className="m-0 list-none p-0">
      {sources.map((s) => (
        <SourceRow key={s.id} source={s} />
      ))}
    </ul>
  )

  if (collapsible) {
    return (
      <Panel className={className}>
        <details className="group">
          <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between px-4 text-[11px] font-semibold tracking-[0.12em] text-brand uppercase">
            Trusted data sources · {TRUSTED_SOURCES.length}
            <span className="text-ink-faint group-open:rotate-180">⌄</span>
          </summary>
          <div className="border-t border-line">{list}</div>
        </details>
      </Panel>
    )
  }

  return (
    <Panel className={className}>
      <PanelHeader title="Trusted data sources" />
      {list}
    </Panel>
  )
}
