import {
  CircleAlert,
  CircleCheck,
  CircleDashed,
  CircleHelp,
  CircleMinus,
  CircleX,
  LoaderCircle,
  MessageCircle,
  type LucideIcon,
} from "lucide-react"

import { cn } from "@/lib/utils"
import { VERDICT_META, type Verdict } from "@/lib/verification"

export const VERDICT_ICONS: Record<Verdict, LucideIcon> = {
  factual: CircleCheck,
  misleading: CircleX,
  "lacks-context": CircleHelp,
  "no-evidence": CircleMinus,
  checking: LoaderCircle,
  error: CircleAlert,
  "no-source": CircleDashed,
  "not-checkable": MessageCircle,
}

export function VerdictIcon({
  verdict,
  className,
}: {
  verdict: Verdict
  className?: string
}) {
  const Icon = VERDICT_ICONS[verdict]
  return (
    <Icon
      aria-label={VERDICT_META[verdict].label}
      className={cn(
        "inline-block shrink-0",
        verdict === "checking" && "animate-spin",
        className
      )}
      style={{ color: VERDICT_META[verdict].color }}
    />
  )
}

export function VerdictBadge({
  verdict,
  size = "sm",
  className,
}: {
  verdict: Verdict
  size?: "sm" | "lg"
  className?: string
}) {
  const meta = VERDICT_META[verdict]
  return (
    <span
      title={meta.description}
      className={cn(
        "inline-flex items-center gap-1 rounded-full font-semibold whitespace-nowrap",
        size === "lg"
          ? "px-3 py-1 text-[13px]"
          : "px-2 py-0.5 text-[11px] leading-4",
        className
      )}
      style={{ backgroundColor: `${meta.color}14`, color: meta.color }}
    >
      <VerdictIcon
        verdict={verdict}
        className={size === "lg" ? "h-4 w-4" : "h-3.5 w-3.5"}
      />
      {meta.label}
    </span>
  )
}
