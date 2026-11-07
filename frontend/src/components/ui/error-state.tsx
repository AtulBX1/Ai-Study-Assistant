import { AlertCircle } from "lucide-react";

export function ErrorState({
  title = "Something went wrong",
  description,
}: {
  title?: string;
  description: string;
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
      </div>
    </div>
  );
}
