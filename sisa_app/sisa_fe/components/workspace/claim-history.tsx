"use client"

import { Dialog } from "@base-ui/react/dialog"
import { ChevronRight, History, X } from "lucide-react"
import { useState } from "react"

import { cn } from "@/lib/utils"
import type { Claim } from "@/hooks/use-claim-detection"
import { ClaimTypeChip } from "@/components/claims/claim-text"
import { claimTime } from "@/components/workspace/current-claim"
import { Panel, PanelHeader } from "@/components/workspace/panel"

function HistoryItems({
  claims,
  currentId,
  onSelect,
}: {
  claims: Claim[]
  currentId?: string
  onSelect: (id: string) => void
}) {
  if (claims.length === 0) {
    return (
      <p className="m-0 px-4 py-5 text-center text-[13px] text-ink-faint">
        Earlier claims from this session will be listed here.
      </p>
    )
  }
  return (
    <ul className="m-0 flex list-none flex-col p-0">
      {claims.map((claim) => (
        <li key={claim.id} className="border-b border-line last:border-b-0">
          <button
            type="button"
            onClick={() => onSelect(claim.id)}
            className={cn(
              "flex w-full flex-col gap-1 px-4 py-2.5 text-left transition-colors hover:bg-canvas",
              claim.id === currentId && "bg-brand/[0.05]"
            )}
          >
            <span className="flex items-center gap-2">
              <ClaimTypeChip type={claim.type} />
              <span className="font-mono text-[10px] text-ink-faint">
                Speaker {claim.speaker}
                {claimTime(claim) ? ` · ${claimTime(claim)}` : ""}
              </span>
            </span>
            <span className="line-clamp-2 text-[13px] leading-snug text-ink">
              {claim.text}
            </span>
          </button>
        </li>
      ))}
    </ul>
  )
}

/** Desktop: a scrollable list in the side column. */
export function ClaimHistoryList({
  claims,
  onSelect,
  className,
}: {
  claims: Claim[]
  onSelect: (id: string) => void
  className?: string
}) {
  return (
    <Panel className={cn("min-h-0", className)}>
      <PanelHeader
        title="Claim history"
        aside={
          <span className="rounded-full bg-canvas px-2 font-mono text-[11px] leading-5 text-ink-muted">
            {claims.length}
          </span>
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <HistoryItems claims={claims} onSelect={onSelect} />
      </div>
    </Panel>
  )
}

/** Mobile: a badge that opens the history as a bottom sheet. */
export function ClaimHistoryBadge({
  claims,
  onSelect,
}: {
  claims: Claim[]
  onSelect: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const count = claims.length

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger
        disabled={count === 0}
        className="flex w-full items-center gap-2 rounded-full border border-line bg-white px-3.5 py-2 text-left text-[13px] text-ink shadow-[0_1px_2px_rgba(15,27,42,0.04)] transition-colors hover:border-brand-accent/50 disabled:cursor-default disabled:opacity-60"
      >
        <History className="h-4 w-4 shrink-0 text-brand-accent" />
        <span className="min-w-0 flex-1 truncate">
          {count === 0 ? (
            "No earlier claims yet"
          ) : (
            <>
              <b className="text-brand">{count}</b> earlier{" "}
              {count === 1 ? "claim" : "claims"} this session
            </>
          )}
        </span>
        {count > 0 ? <ChevronRight className="h-4 w-4 text-ink-faint" /> : null}
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-40 bg-ink/40 transition-opacity data-[ending-style]:opacity-0 data-[starting-style]:opacity-0" />
        <Dialog.Popup className="fixed inset-x-0 bottom-0 z-50 flex max-h-[80svh] flex-col rounded-t-2xl bg-white shadow-2xl transition-transform duration-200 data-[ending-style]:translate-y-full data-[starting-style]:translate-y-full sm:inset-x-auto sm:top-1/2 sm:left-1/2 sm:w-[440px] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-2xl">
          <div className="mx-auto mt-2 h-1 w-10 rounded-full bg-line sm:hidden" />
          <div className="flex items-center justify-between border-b border-line px-4 py-3">
            <Dialog.Title className="m-0 text-[13px] font-semibold tracking-[0.08em] text-brand uppercase">
              Claim history · {count}
            </Dialog.Title>
            <Dialog.Close
              aria-label="Close"
              className="rounded-full p-1 text-ink-muted hover:bg-canvas"
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto pb-[env(safe-area-inset-bottom)]">
            <HistoryItems
              claims={claims}
              onSelect={(id) => {
                onSelect(id)
                setOpen(false)
              }}
            />
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
