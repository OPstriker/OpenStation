import { Link } from "@tanstack/react-router"
import { Wind } from "lucide-react"

import { cn } from "@/lib/utils"

interface LogoProps {
  variant?: "full" | "icon" | "responsive"
  className?: string
  asLink?: boolean
}

export function Logo({
  variant = "full",
  className,
  asLink = true,
}: LogoProps) {
  const content = (
    <span
      className={cn(
        "flex items-center gap-2 font-semibold text-foreground",
        className,
      )}
    >
      <Wind className="size-5 shrink-0 text-primary" aria-hidden="true" />
      {variant !== "icon" && (
        <span
          className={cn(
            "truncate",
            variant === "responsive" && "group-data-[collapsible=icon]:hidden",
          )}
        >
          Weather Station
        </span>
      )}
      {variant === "icon" && <span className="sr-only">Weather Station</span>}
    </span>
  )

  if (!asLink) {
    return content
  }

  return (
    <Link to="/" aria-label="Weather Station home">
      {content}
    </Link>
  )
}
