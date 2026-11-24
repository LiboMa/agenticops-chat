import * as RadixSwitch from "@radix-ui/react-switch";
import { cn } from "@/lib/cn";

interface SwitchProps {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  /** id of the visible setting name — preferred over `label` */
  labelledBy?: string;
  /** id of the visible description */
  describedBy?: string;
  /** the accessible name when no visible name exists */
  label?: string;
  disabled?: boolean;
  className?: string;
}

/** The one on/off control (MVP-2.8.0 S1): role="switch" + aria-checked (Radix), a name and a description, the
 *  keyboard (Space / Enter), a visible focus ring, and a ≥ 44 px hit area on a touch screen. */
export function Switch({ checked, onCheckedChange, labelledBy, describedBy, label, disabled, className }: SwitchProps) {
  return (
    <RadixSwitch.Root
      checked={checked}
      onCheckedChange={onCheckedChange}
      disabled={disabled}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      aria-label={labelledBy ? undefined : label}
      className={cn(
        "relative inline-flex h-5 w-10 shrink-0 items-center rounded-full transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background",
        "data-[state=checked]:bg-primary data-[state=unchecked]:bg-muted-foreground/30",
        "disabled:cursor-not-allowed disabled:opacity-50",
        // a 44 px touch target without growing the drawn switch
        "before:absolute before:-inset-x-1 before:-inset-y-3 before:content-['']",
        className,
      )}
    >
      <RadixSwitch.Thumb
        className="pointer-events-none block h-4 w-4 rounded-full bg-background shadow-sm transition-transform data-[state=checked]:translate-x-[22px] data-[state=unchecked]:translate-x-0.5"
      />
    </RadixSwitch.Root>
  );
}
