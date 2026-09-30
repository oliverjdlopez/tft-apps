import React, { createContext, useContext, useId, useRef, useState } from "react";
import { CircleHelp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";

const HelpContext = createContext(null);

/** Keep one parameter explanation open across the composition workspace. */
export function ParameterHelpProvider({ children }) {
  const [selected, setSelected] = useState(null);
  const current = useRef(selected);
  current.current = selected;
  return <HelpContext.Provider value={{ selected, setSelected, current }}>{children}</HelpContext.Provider>;
}

/** Show parameter help on activation with collision-aware positioning and focus return. */
export default function ParameterLabel({ children, help }) {
  const context = useContext(HelpContext);
  const id = useId();
  const trigger = useRef(null);
  const close = useRef(null);
  return (
    <span className="composition-parameter-label">
      {children}
      <Popover open={context?.selected === id} onOpenChange={(open) => context?.setSelected(open ? id : null)}>
        <PopoverTrigger asChild>
          <Button ref={trigger} type="button" variant="ghost" size="icon-sm" className="size-6" aria-label={`About ${children}`}
            onClick={(event) => {
              // Help icons live inside field labels; suppress the label's input activation.
              event.preventDefault();
              context?.setSelected(context.selected === id ? null : id);
            }}>
            <CircleHelp className="size-4" />
          </Button>
        </PopoverTrigger>
        <PopoverContent aria-labelledby={`${id}-title`} align="start" className="w-80 max-w-[calc(100vw-24px)]"
          onOpenAutoFocus={(event) => { event.preventDefault(); close.current?.focus(); }}
          onCloseAutoFocus={(event) => { event.preventDefault(); if (!context?.current.current) trigger.current?.focus(); }}>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h2 id={`${id}-title`} className="font-semibold">{children}</h2>
            <Button ref={close} type="button" variant="ghost" size="sm" aria-label="Close parameter help" onClick={() => context?.setSelected(null)}>Close</Button>
          </div>
          <p className="text-sm text-muted-foreground">{help}</p>
        </PopoverContent>
      </Popover>
    </span>
  );
}
