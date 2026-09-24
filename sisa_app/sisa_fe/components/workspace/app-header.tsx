import { cn } from "@/lib/utils"
import { SourcesButton } from "@/components/workspace/trusted-sources"

export function AppHeader({
  live,
  claimCount,
}: {
  live: boolean
  claimCount: number
}) {
  return (
    <header className="shrink-0 bg-brand text-white">
      <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-3 sm:px-6">
        <span className="text-lg font-bold tracking-[0.24em] sm:text-xl">
          SISA
        </span>
        <span aria-hidden className="h-5 w-px shrink-0 bg-white/30" />
        <p className="m-0 min-w-0 truncate text-[13px] text-white/75 sm:text-sm">
          Live claim detection for Philippine public speech
        </p>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <span className="hidden text-xs text-white/70 md:inline">
            {claimCount} {claimCount === 1 ? "claim" : "claims"} this session
          </span>
          <SourcesButton />
          <span
            className={cn(
              "flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium",
              live ? "bg-white text-brand" : "bg-white/10 text-white/80"
            )}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 rounded-full",
                live ? "animate-pulse bg-[#E4572E]" : "bg-white/60"
              )}
            />
            {live ? "Live" : "Idle"}
          </span>
        </div>
      </div>
    </header>
  )
}
