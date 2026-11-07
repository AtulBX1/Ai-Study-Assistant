"use client";

import { Toaster } from "sonner";

export function Toast() {
  return (
    <Toaster
      position="top-right"
      richColors
      closeButton
      toastOptions={{
        classNames: {
          toast: "border border-border bg-card text-card-foreground",
        },
      }}
    />
  );
}
