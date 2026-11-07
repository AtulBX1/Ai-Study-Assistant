"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { ErrorState } from "@/components/ui/error-state";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  getPublicProfile,
  updatePublicProfile,
} from "@/lib/documents";
import { updateCurrentUserProfile } from "@/lib/session";

export function ProfileSettings() {
  const queryClient = useQueryClient();
  const profile = useQuery({
    queryKey: ["public-profile"],
    queryFn: getPublicProfile,
  });
  const [handle, setHandle] = useState("");
  const [showOnLeaderboards, setShowOnLeaderboards] = useState(true);
  const [validationError, setValidationError] = useState<string | null>(null);

  useEffect(() => {
    if (!profile.data) return;
    setHandle(profile.data.public_handle);
    setShowOnLeaderboards(profile.data.show_on_leaderboards);
  }, [profile.data]);

  const update = useMutation({
    mutationFn: updatePublicProfile,
    onSuccess: async (value, input) => {
      const current = profile.data;
      const next = {
        public_handle:
          input.public_handle ?? current?.public_handle ?? handle,
        show_on_leaderboards:
          input.show_on_leaderboards ??
          current?.show_on_leaderboards ??
          showOnLeaderboards,
      };
      queryClient.setQueryData(["public-profile"], next);
      updateCurrentUserProfile(next);
      setValidationError(null);
      toast.success("Profile settings saved.");
      await queryClient.invalidateQueries({ queryKey: ["public-profile"] });
      void value;
    },
  });

  const save = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setValidationError(null);
    const normalized = handle.trim();
    if (normalized.length < 3 || normalized.length > 20) {
      setValidationError("Handle must be between 3 and 20 characters.");
      return;
    }
    if (!/^[A-Za-z0-9_-]+$/.test(normalized)) {
      setValidationError(
        "Use only letters, numbers, underscores, and hyphens in your handle.",
      );
      return;
    }
    const current = profile.data;
    if (!current) return;
    const input: { public_handle?: string; show_on_leaderboards?: boolean } = {};
    if (normalized !== current.public_handle) input.public_handle = normalized;
    if (showOnLeaderboards !== current.show_on_leaderboards) {
      input.show_on_leaderboards = showOnLeaderboards;
    }
    if (Object.keys(input).length === 0) {
      toast.success("No profile changes to save.");
      return;
    }
    update.mutate(input);
  };

  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold">Public profile</h2>
        <p className="text-sm text-muted-foreground">
          Your handle is visible on leaderboards. It can be changed once every
          30 days. Email is only shown in your own account settings.
        </p>
      </CardHeader>
      <CardContent>
        {profile.isLoading ? (
          <p role="status" className="text-sm text-muted-foreground">
            Loading profile settings…
          </p>
        ) : profile.isError ? (
          <ErrorState
            title="Could not load profile settings"
            description={profile.error.message}
          />
        ) : (
          <form onSubmit={save} className="space-y-5">
            <div className="space-y-2">
              <Label htmlFor="public-handle">Public handle</Label>
              <Input
                id="public-handle"
                name="public_handle"
                value={handle}
                minLength={3}
                maxLength={20}
                onChange={(event) => setHandle(event.target.value)}
                aria-describedby="public-handle-hint"
                required
              />
              <p id="public-handle-hint" className="text-xs text-muted-foreground">
                3–20 letters, numbers, underscores, or hyphens. The server checks
                uniqueness and the change cooldown.
              </p>
            </div>
            <label className="flex items-start gap-3 text-sm">
              <input
                type="checkbox"
                checked={showOnLeaderboards}
                onChange={(event) => setShowOnLeaderboards(event.target.checked)}
                className="mt-0.5 size-4 accent-primary focus-visible:ring-2 focus-visible:ring-primary"
              />
              <span>
                <span className="font-medium">Show me on leaderboards</span>
                <span className="mt-1 block text-xs text-muted-foreground">
                  When off, your score may still contribute anonymously to
                  aggregate statistics.
                </span>
              </span>
            </label>
            {validationError ? (
              <ErrorState title="Check your handle" description={validationError} />
            ) : null}
            {update.isError ? (
              <ErrorState
                title="Could not save profile settings"
                description={update.error.message}
              />
            ) : null}
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? "Saving…" : "Save profile settings"}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
