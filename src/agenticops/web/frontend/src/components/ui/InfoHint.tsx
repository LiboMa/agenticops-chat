import { useState } from "react";
import * as Tooltip from "@radix-ui/react-tooltip";
import { Info } from "lucide-react";

/** A metric's definition behind an ⓘ (MVP-2.9.0 N24, the 2.8.0 spec's R17): shown on hover and keyboard focus, and
 *  on a tap — a touch screen has no hover. `label` names the button («Definition: total cost»); the definition is
 *  what describes it while it is open. Escape, a tap elsewhere and leaving it close it (Radix). */
export function InfoHint({ label, text }: { label: string; text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Tooltip.Provider delayDuration={200}>
      <Tooltip.Root open={open} onOpenChange={setOpen}>
        <Tooltip.Trigger asChild>
          {/* a click shows it and must not reach Radix's own handler, which closes a tooltip on click */}
          <button type="button" aria-label={label}
                  onClick={(e) => { e.preventDefault(); setOpen(true); }}
                  className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full align-middle text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
            <Info className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content side="top" sideOffset={4} collisionPadding={8}
                           className="z-[60] max-w-[260px] rounded-md bg-foreground px-2.5 py-1.5 text-xs font-normal normal-case leading-relaxed tracking-normal text-background shadow-md">
            {text}
            <Tooltip.Arrow className="fill-foreground" />
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}
