"use client";

import { useState, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Tabs({
  tabs,
}: {
  tabs: Array<{ id: string; label: string; content: ReactNode }>;
}) {
  const [selected, setSelected] = useState(tabs[0]?.id ?? "");
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const currentIndex = tabs.findIndex((tab) => tab.id === selected);
    const nextIndex =
      event.key === "ArrowRight"
        ? (currentIndex + 1) % tabs.length
        : event.key === "ArrowLeft"
          ? (currentIndex - 1 + tabs.length) % tabs.length
          : currentIndex;
    if (nextIndex !== currentIndex) {
      event.preventDefault();
      const next = tabs[nextIndex];
      setSelected(next.id);
      document.getElementById(`tab-${next.id}`)?.focus();
    }
  };

  return (
    <div>
      <div role="tablist" aria-label="Content tabs" className="flex gap-1 border-b border-border">
        {tabs.map((tab) => (
          <button
            id={`tab-${tab.id}`}
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selected === tab.id}
            aria-controls={`panel-${tab.id}`}
            tabIndex={selected === tab.id ? 0 : -1}
            onClick={() => setSelected(tab.id)}
            onKeyDown={onKeyDown}
            className={cn(
              "rounded-t-md px-4 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
              selected === tab.id
                ? "border-b-2 border-primary text-foreground"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>
      {tabs.map((tab) =>
        tab.id === selected ? (
          <div
            key={tab.id}
            id={`panel-${tab.id}`}
            role="tabpanel"
            aria-labelledby={`tab-${tab.id}`}
            tabIndex={0}
            className="pt-4 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            {tab.content}
          </div>
        ) : null,
      )}
    </div>
  );
}
