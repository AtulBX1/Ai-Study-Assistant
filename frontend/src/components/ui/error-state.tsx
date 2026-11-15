import { AlertCircle } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

export function ErrorState({
  title = "Something went wrong",
  description,
  action,
}: {
  title?: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div
      role="alert"
      className="flex items-start gap-3 rounded-lg border border-danger/30 bg-danger/5 p-4 text-danger"
    >
      <AlertCircle className="mt-0.5 shrink-0" size={18} aria-hidden="true" />
      <div>
        <h2 className="font-medium">{title}</h2>
        <p className="mt-1 text-sm leading-5">{description}</p>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          {action}
          <Button type="button" size="sm" variant="outline" onClick={() => window.location.reload()}>
            Retry
          </Button>
        </div>
      </div>
    </div>
  );
}
