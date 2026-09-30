import React from "react";
import { ChevronRight } from "lucide-react";
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from "@/components/ui/collapsible";
import { Button } from "@/components/ui/button";

/** Mark the heading of an application disclosure while preserving its content. */
export function DisclosureSummary({ children, ...props }) {
  return <span {...props}>{children}</span>;
}

/** Replace native details with shared controls while keeping hidden children mounted. */
export function Disclosure({ children, open = false, className }) {
  const parts = React.Children.toArray(children);
  const heading = parts.find((child) => React.isValidElement(child) && child.type === DisclosureSummary);
  return (
    <Collapsible defaultOpen={open} className={className}>
      <CollapsibleTrigger asChild>
        <Button type="button" variant="ghost" className="group my-2 h-auto w-full justify-start whitespace-normal text-left">
          <ChevronRight className="size-4 group-data-[state=open]:rotate-90" />{heading}
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent forceMount className="min-w-0 space-y-3 p-3 data-[state=closed]:hidden">
        {parts.filter((child) => child !== heading)}
      </CollapsibleContent>
    </Collapsible>
  );
}
