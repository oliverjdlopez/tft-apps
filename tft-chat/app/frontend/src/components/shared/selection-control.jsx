import React from "react";
import { Checkbox } from "@/components/ui/checkbox";

/** Preserve A2UI's native radio-group events while sharing checkbox and focus styling. */
export function SelectionControl({ type, onChange, ...props }) {
  if (type !== "radio") return <Checkbox {...props} onCheckedChange={() => onChange?.()} />;
  // Native radios retain group arrow-key navigation and do not toggle off on a second click.
  return <span className="relative inline-flex size-4 shrink-0">
    <input type="radio" className="peer sr-only" onChange={onChange} {...props} />
    <span aria-hidden="true" className="size-4 rounded-full border border-input bg-input/30 peer-checked:border-primary peer-checked:after:absolute peer-checked:after:inset-1 peer-checked:after:rounded-full peer-checked:after:bg-primary peer-focus-visible:ring-[3px] peer-focus-visible:ring-ring/50 peer-disabled:opacity-50" />
  </span>;
}
