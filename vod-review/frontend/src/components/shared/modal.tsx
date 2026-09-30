import { useRef, type ReactNode } from "react";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { AlertDialog, AlertDialogContent, AlertDialogTitle } from "@/components/ui/alert-dialog";

/** Supply focus management for existing conditionally mounted video dialogs. */
export function Modal({ title, onOpenChange, children, destructive = false }: {
  title: string;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
  destructive?: boolean;
}) {
  // These dialogs are opened by several existing actions, not one DialogTrigger.
  const origin = useRef(document.activeElement as HTMLElement | null);
  const restoreFocus = (event: Event) => { event.preventDefault(); origin.current?.focus(); };
  if (destructive) return (
    <AlertDialog open onOpenChange={onOpenChange}>
      <AlertDialogContent aria-describedby={undefined} onCloseAutoFocus={restoreFocus}>
        <AlertDialogTitle className="sr-only">{title}</AlertDialogTitle>
        {children}
      </AlertDialogContent>
    </AlertDialog>
  );
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false} aria-describedby={undefined} onCloseAutoFocus={restoreFocus}>
        <DialogTitle className="sr-only">{title}</DialogTitle>
        {children}
      </DialogContent>
    </Dialog>
  );
}
