import { cn } from "@/lib/utils"

/** Render the shared Skeleton primitive with shadcn styling and accessible behavior. */
function Skeleton({
  className,
  ...props
}) {
  return (
    <div
      data-slot="skeleton"
      className={cn("animate-pulse rounded-md bg-accent", className)}
      {...props}
    />
  )
}

export { Skeleton }
