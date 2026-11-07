"use client";

import { useRouter } from "next/navigation";
import { LogOut, MoonStar } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/ui/page-header";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ThemeToggle } from "@/components/theme-toggle";
import { useMe } from "@/lib/hooks/use-me";
import { logoutUser } from "@/lib/auth";

export default function SettingsPage() {
  const { data: user } = useMe();
  const router = useRouter();

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
    <>
      <PageHeader
        title="Settings"
        description="Manage your personal study experience and account."
      />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <div className="flex items-center gap-2">
              <MoonStar size={18} className="text-primary" aria-hidden="true" />
              <h2 className="font-semibold">Appearance</h2>
            </div>
            <p className="text-sm text-muted-foreground">
              Choose a comfortable light or dark study space.
            </p>
          </CardHeader>
          <CardContent>
            <ThemeToggle />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <h2 className="font-semibold">Your account</h2>
            <p className="text-sm text-muted-foreground">
              Your public handle is shown in the app navigation.
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Public handle
              </p>
              <p className="mt-1 font-medium">{user?.public_handle}</p>
            </div>
            <div>
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Email
              </p>
              <p className="mt-1 break-all font-medium">{user?.email}</p>
            </div>
            {user?.role === "admin" ? <Badge>Administrator</Badge> : null}
            <div className="border-t border-border pt-4">
              <Button type="button" variant="outline" onClick={handleLogout}>
                <LogOut size={16} aria-hidden="true" />
                Log out
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </>
  );
}
