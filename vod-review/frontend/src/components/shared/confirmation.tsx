import { useEffect, useRef, useState } from "react";
import { AlertDialog, AlertDialogContent, AlertDialogTitle, AlertDialogDescription, AlertDialogFooter, AlertDialogCancel, AlertDialogAction } from "@/components/ui/alert-dialog";

type PendingConfirmation = { message: string; resolve: (accepted: boolean) => void; origin: HTMLElement | null };

/** Ask before an existing destructive or expensive action, defaulting focus to Cancel. */
export function useConfirmation() {
  const [pending, setPending] = useState<PendingConfirmation | null>(null);
  const current = useRef<PendingConfirmation | null>(null);
  useEffect(() => () => current.current?.resolve(false), []);
  /** Resolve the pending operation exactly once when either action dismisses the dialog. */
  function finish(accepted: boolean) {
    current.current?.resolve(accepted);
    current.current = null;
    setPending(null);
  }
  /** Suspend the caller until the user explicitly accepts or dismisses the confirmation. */
  function confirm(message: string): Promise<boolean> {
    current.current?.resolve(false);
    return new Promise((resolve) => {
      const next = { message, resolve, origin: document.activeElement as HTMLElement | null };
      current.current = next;
      setPending(next);
    });
  }
  const confirmation = pending && <AlertDialog open onOpenChange={(open) => { if (!open) finish(false); }}>
    <AlertDialogContent onCloseAutoFocus={(event) => { event.preventDefault(); pending.origin?.focus(); }}>
      <AlertDialogTitle>Confirm action</AlertDialogTitle>
      <AlertDialogDescription>{pending.message}</AlertDialogDescription>
      <AlertDialogFooter>
        <AlertDialogCancel onClick={() => finish(false)}>Cancel</AlertDialogCancel>
        <AlertDialogAction onClick={() => finish(true)}>Continue</AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  </AlertDialog>;
  return { confirm, confirmation };
}
