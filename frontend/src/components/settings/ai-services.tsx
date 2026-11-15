"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { apiBaseUrl } from "@/lib/api";
import { getAccessToken } from "@/lib/session";

type FeatureStatus = { provider: string; model: string; state: string; cooldown_seconds: number };
const features = ["chat", "quiz", "flashcards", "summary", "syllabus"] as const;

export function AIServices({ initialLocalOnly = false }: { initialLocalOnly?: boolean }) {
  const [localOnly, setLocalOnly] = useState(initialLocalOnly);
  useEffect(() => setLocalOnly(initialLocalOnly), [initialLocalOnly]);
  const status = useQuery({
    queryKey: ["ai-status"],
    queryFn: async () => {
      const response = await fetch(`${apiBaseUrl}/system/ai-status`);
      if (!response.ok) throw new Error("AI service status is unavailable.");
      return (await response.json()) as { features: Record<string, FeatureStatus> };
    },
  });

  return <section className="lg:col-span-2 rounded-lg border border-border bg-card p-5">
    <h2 className="font-semibold">AI services</h2>
    <p className="mt-1 text-sm text-muted-foreground">Provider readiness for each study feature. API keys are never shown.</p>
    <div className="mt-4 overflow-x-auto">
      <table className="w-full text-left text-sm"><thead><tr><th className="py-2">Feature</th><th>Provider / model</th><th>State</th></tr></thead>
        <tbody>{features.map((feature) => {
          const item = status.data?.features?.[feature];
          return <tr key={feature} className="border-t border-border"><td className="py-2 capitalize">{feature}</td><td>{item ? `${item.provider} / ${item.model}` : "Loading"}</td><td>{item?.state ?? "—"}{item?.cooldown_seconds ? ` (${item.cooldown_seconds}s)` : ""}</td></tr>;
        })}</tbody>
      </table>
    </div>
    <label className="mt-4 flex items-center gap-3 text-sm font-medium">
      <input type="checkbox" checked={localOnly} onChange={async (event) => {
        const value = event.target.checked;
        setLocalOnly(value);
        try {
          const response = await fetch(`${apiBaseUrl}/auth/ai-settings`, { method: "PATCH", headers: { "Content-Type": "application/json", Authorization: `Bearer ${getAccessToken() ?? ""}` }, body: JSON.stringify({ local_models_only: value }) });
          if (!response.ok) throw new Error();
        } catch { setLocalOnly(!value); }
      }} />
      Local models only
    </label>
  </section>;
}
