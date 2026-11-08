"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "@/components/ui/button";

export function Dialog({
  open,
  onOpenChange,
  title,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
    }
    if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
    }
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby="dialog-title"
      onCancel={(event) => {
        event.preventDefault();
        onOpenChange(false);
      }}
      onClick={(event) => {
        if (event.target === ref.current) onOpenChange(false);
      }}
      className="w-[calc(100%-2rem)] max-w-lg rounded-xl border border-border bg-card p-0 text-card-foreground shadow-xl backdrop:bg-foreground/30"
    >
      <div className="flex items-center justify-between border-b border-border px-6 py-4">
        <h2 id="dialog-title" className="font-semibold">{title}</h2>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label="Close dialog"
          onClick={() => onOpenChange(false)}
        >
          <X size={18} aria-hidden="true" />
        </Button>
      </div>
      <div className="p-6">{children}</div>
    </dialog>
  );
}
