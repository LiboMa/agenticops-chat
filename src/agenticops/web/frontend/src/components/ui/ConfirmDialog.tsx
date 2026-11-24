import { useEffect, useRef, useCallback, useState } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useLocale } from "@/i18n/LocaleContext";
import { returnFocusTo } from "@/lib/focusReturn";

interface ConfirmDialogProps {
  message: string;
  title?: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "default" | "destructive";
  onConfirm: () => void;
  onCancel: () => void;
}

/** A yes / no question (MVP-2.8.0 S2 rework). A Radix dialog with role=alertdialog, so it stacks on another Radix
 *  layer — inside the chat-list drawer a hand-made portal got `pointer-events: none` from the drawer's modal and
 *  its focus pulled back into the drawer, so «删除» could not be pressed (review). Radix keeps Tab inside and makes
 *  only this layer clickable; focus goes back to whatever had it when it opened (lib/focusReturn); one ESC closes
 *  only this dialog, never the panel under it. */
export function ConfirmDialog({
  message,
  title,
  confirmText = "Confirm",
  cancelText = "Cancel",
  variant = "default",
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const openerRef = useRef<HTMLElement | null>(
    typeof document !== "undefined" && document.activeElement instanceof HTMLElement && document.activeElement !== document.body
      ? document.activeElement : null,
  );

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation(); // one ESC closes only this dialog, not the panel under it (as ReasonDialog, F7)
      onCancel();
    };
    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  }, [onCancel]);

  return (
    <Dialog.Root open onOpenChange={(open) => { if (!open) onCancel(); }}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[60] grid place-items-center bg-black/50 px-4 backdrop-blur-sm">
          <Dialog.Content role="alertdialog"
                          onOpenAutoFocus={(e) => { e.preventDefault(); cancelRef.current?.focus(); }}
                          onCloseAutoFocus={(e) => returnFocusTo(openerRef.current, e)}
                          className="relative w-full max-w-sm rounded-lg border border-border bg-card p-6 shadow-lg animate-in fade-in zoom-in-95 duration-150">
            {title
              ? <Dialog.Title className="mb-1 text-base font-semibold text-foreground">{title}</Dialog.Title>
              : <Dialog.Title className="sr-only">{confirmText}</Dialog.Title>}
            <Dialog.Description className="mb-6 text-sm text-muted-foreground [overflow-wrap:anywhere]">{message}</Dialog.Description>
            <div className="flex justify-end gap-2">
              <button
                ref={cancelRef}
                type="button"
                onClick={onCancel}
                className="px-4 py-2 text-sm font-medium rounded-lg border border-border text-muted-foreground bg-background hover:bg-secondary transition-colors"
              >
                {cancelText}
              </button>
              <button
                type="button"
                onClick={onConfirm}
                className={`px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
                  variant === "destructive"
                    ? "bg-red-600 text-white hover:bg-red-700"
                    : "bg-primary text-primary-foreground hover:bg-primary/90"
                }`}
              >
                {confirmText}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

interface ConfirmOptions {
  title?: string;
  confirmText?: string;
  cancelText?: string;
  variant?: "default" | "destructive";
}

export function useConfirm() {
  const { t } = useLocale();   // the buttons in the page's language unless a caller names them (it read «Cancel» in zh)
  const [state, setState] = useState<(ConfirmOptions & { message: string }) | null>(null);
  const resolveRef = useRef<(v: boolean) => void>();

  const confirm = useCallback((message: string, options?: ConfirmOptions): Promise<boolean> => {
    return new Promise<boolean>((resolve) => {
      resolveRef.current = resolve;
      setState({ message, ...options });
    });
  }, []);

  const handleConfirm = useCallback(() => {
    resolveRef.current?.(true);
    setState(null);
  }, []);

  const handleCancel = useCallback(() => {
    resolveRef.current?.(false);
    setState(null);
  }, []);

  const dialog = state ? (
    <ConfirmDialog
      message={state.message}
      title={state.title}
      confirmText={state.confirmText ?? t("common.confirm")}
      cancelText={state.cancelText ?? t("common.cancel")}
      variant={state.variant}
      onConfirm={handleConfirm}
      onCancel={handleCancel}
    />
  ) : null;

  return { confirm, dialog };
}
