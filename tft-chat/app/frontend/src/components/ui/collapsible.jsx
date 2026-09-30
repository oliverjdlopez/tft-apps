import { Collapsible as CollapsiblePrimitive } from "radix-ui"

/** Render the shared Collapsible primitive with shadcn styling and accessible behavior. */
function Collapsible({
  ...props
}) {
  return <CollapsiblePrimitive.Root data-slot="collapsible" {...props} />
}

/** Render the shared CollapsibleTrigger primitive with shadcn styling and accessible behavior. */
function CollapsibleTrigger({
  ...props
}) {
  return (
    <CollapsiblePrimitive.CollapsibleTrigger
      data-slot="collapsible-trigger"
      {...props}
    />
  )
}

/** Render the shared CollapsibleContent primitive with shadcn styling and accessible behavior. */
function CollapsibleContent({
  ...props
}) {
  return (
    <CollapsiblePrimitive.CollapsibleContent
      data-slot="collapsible-content"
      {...props}
    />
  )
}

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
