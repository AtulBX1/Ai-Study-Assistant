"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  Activity,
  BookOpen,
  BrainCircuit,
  ChartNoAxesCombined,
  ClipboardList,
  FlaskConical,
  Layers3,
  Library,
  LogOut,
  Menu,
  MessageSquareText,
  Settings,
  Sparkles,
} from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { logoutUser } from "@/lib/auth";
import { useAuth } from "@/providers/auth-provider";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import type { ReactNode } from "react";

const navigation = [
  { label: "Library", href: "/library", icon: Library },
  { label: "Chat", href: "/chat", icon: MessageSquareText },
  { label: "Quizzes", href: "/quizzes", icon: ClipboardList },
  { label: "Flashcards", href: "/flashcards", icon: Layers3 },
  { label: "Study Tools", href: "/study-tools", icon: Sparkles },
  { label: "Test Library", href: "/test-library", icon: BookOpen },
  { label: "My Progress", href: "/progress", icon: ChartNoAxesCombined },
  { label: "Lab", href: "/lab", icon: FlaskConical },
  { label: "Benchmarks", href: "/benchmarks", icon: Activity },
  { label: "Settings", href: "/settings", icon: Settings },
];

export function NavigationLinks({
  isAdmin,
  onNavigate,
}: {
  isAdmin: boolean;
  onNavigate: () => void;
}) {
  const pathname = usePathname();
  const items = isAdmin
    ? [...navigation, { label: "Admin", href: "/admin", icon: BrainCircuit }]
    : navigation;
  return (
    <nav aria-label="Main navigation" className="space-y-1">
      {items.map(({ label, href, icon: Icon }) => {
        const active = pathname === href || (href !== "/" && pathname.startsWith(`${href}/`));
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            onClick={onNavigate}
            className={cn(
              "flex min-h-10 items-center gap-3 rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
              active
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
          >
            <Icon size={18} aria-hidden="true" />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

function Sidebar({ isAdmin, onNavigate }: { isAdmin: boolean; onNavigate: () => void }) {
  return (
    <div className="flex h-full flex-col bg-card px-4 py-5">
      <Link
        href="/"
        onClick={onNavigate}
        className="mb-8 flex items-center gap-2 rounded-md px-2 font-semibold tracking-tight focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
        <span className="grid size-9 place-items-center rounded-xl bg-primary text-primary-foreground">
          <BrainCircuit size={19} aria-hidden="true" />
        </span>
        <span>StudyMate</span>
      </Link>
      <NavigationLinks isAdmin={isAdmin} onNavigate={onNavigate} />
      <p className="mt-auto px-2 pt-8 text-xs leading-5 text-muted-foreground">
        A calm space to learn from your course material.
      </p>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const { user } = useAuth();
  const router = useRouter();
  const isAdmin = user?.role === "admin";

  const handleLogout = async () => {
    try {
      await logoutUser();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Could not log out.");
    } finally {
      router.replace("/login");
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <aside className="fixed inset-y-0 left-0 z-20 hidden w-64 border-r border-border lg:block">
        <Sidebar isAdmin={isAdmin} onNavigate={() => undefined} />
      </aside>
      <div className="lg:pl-64">
        <header className="sticky top-0 z-10 flex h-16 items-center justify-between border-b border-border bg-background/95 px-4 backdrop-blur sm:px-6">
          <div className="flex items-center gap-3">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="lg:hidden"
              aria-label="Open navigation"
              onClick={() => setDrawerOpen(true)}
            >
              <Menu size={18} aria-hidden="true" />
            </Button>
            <span className="hidden text-sm text-muted-foreground sm:inline">
              Your personal study space
            </span>
          </div>
          <details className="relative">
            <summary className="flex min-h-10 cursor-pointer list-none items-center gap-2 rounded-md px-3 text-sm font-medium hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary [&::-webkit-details-marker]:hidden">
              <span className="grid size-7 place-items-center rounded-full bg-primary/10 text-xs font-semibold text-primary">
                {user?.public_handle.slice(0, 1).toUpperCase()}
              </span>
              <span>{user?.public_handle}</span>
            </summary>
            <div className="absolute right-0 mt-2 w-52 rounded-lg border border-border bg-card p-2 shadow-lg">
              <Button
                type="button"
                variant="ghost"
                className="w-full justify-start"
                onClick={handleLogout}
              >
                <LogOut size={16} aria-hidden="true" />
                Log out
              </Button>
            </div>
          </details>
        </header>
        <main className="mx-auto min-h-[calc(100vh-4rem)] max-w-7xl p-4 sm:p-8">
          {children}
        </main>
      </div>
      <Dialog
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        title="Navigation"
      >
        <div className="-m-2">
          <Sidebar isAdmin={isAdmin} onNavigate={() => setDrawerOpen(false)} />
        </div>
      </Dialog>
    </div>
  );
}
