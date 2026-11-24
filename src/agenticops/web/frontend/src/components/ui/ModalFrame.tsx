import { useRef } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useLocale } from "@/i18n/LocaleContext";
import { returnFocusTo } from "@/lib/focusReturn";

/** A modal dialog frame (MVP-2.8.0; first written for the user management page, shared since the API key page):
 *  Radix — slides in, ESC closes, focus kept inside; mounted on open, so the element focused at the first render is
 *  the opener and gets focus back (lib/focusReturn). `width` is a Tailwind width class. */

function useOpener() {
  return useRef<HTMLElement | null>(
    typeof document !== "undefined" && document.activeElement instanceof HTMLElement && document.activeElement !== document.body
      ? document.activeElement : null,
  );
}

export function ModalFrame({ title, onClose, returnTo, keepOnOutside = false, width = "w-[min(440px,100%)]", children }: {
  title: string; onClose: () => void; children: React.ReactNode;
  /** a click outside does not close it (the one-time password: a stray click lost its only copy — S2 rework review) */
  keepOnOutside?: boolean;
  /** where focus goes on close when the dialog was not opened by the focused element (the one-time password opens
   *  after another dialog or a confirm closed — the flow's own button, S2 rework E2E) */
  returnTo?: HTMLElement | null;
  width?: string;
}) {
  const { t } = useLocale();
  const focused = useOpener();
  const opener = { current: returnTo ?? focused.current };
  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onClose(); }}>
      <Dialog.Portal>
        {/* centred by the overlay, not by a translate: the slideInRight keyframe owns `transform` */}
        <Dialog.Overlay className="fixed inset-0 z-50 grid items-start justify-items-center overflow-y-auto bg-black/30 px-4 pt-[12vh]">
          <Dialog.Content aria-describedby={undefined} onCloseAutoFocus={(e) => returnFocusTo(opener.current, e)}
                          onPointerDownOutside={keepOnOutside ? (e) => e.preventDefault() : undefined}
                          className={`${width} rounded-lg border border-border bg-card p-5 shadow-xl animate-[slideInRight_0.2s_ease-out]`}>
            <div className="flex items-start justify-between gap-3">
              <Dialog.Title className="text-lg font-semibold text-foreground [overflow-wrap:anywhere]">{title}</Dialog.Title>
              <Dialog.Close aria-label={t("common.close")} className="rounded px-2 text-lg text-muted-foreground hover:text-foreground">×</Dialog.Close>
            </div>
            {children}
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
