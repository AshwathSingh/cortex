"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import {
  SettingsSection,
  SettingsValue,
} from "@/components/settings/settings-section";
import {
  SettingsRow,
  UnavailableAction,
} from "@/components/settings/settings-row";
import { Button } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { PageHeader, PageShell } from "@/components/ui/page-layout";
import { ApiError, apiRequest } from "@/lib/api";
import type { AuthenticatedUser } from "@/lib/api-types";

type AccountSettingsProps = {
  user: AuthenticatedUser | null;
  backHref?: string;
  backLabel?: string;
  loadError?: string | null;
};

function accountInitials(user: AuthenticatedUser | null) {
  const label = user?.display_name?.trim() || user?.email || "Account";
  const parts = label
    .replace(/@.*$/, "")
    .split(/[\s._-]+/)
    .filter(Boolean);

  return (
    parts
      .slice(0, 2)
      .map((part) => part[0]?.toUpperCase())
      .join("") || "A"
  );
}

export function AccountSettings({
  user,
  backHref,
  backLabel,
  loadError,
}: AccountSettingsProps) {
  const router = useRouter();
  const [isLoggingOut, setIsLoggingOut] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function logout() {
    setIsLoggingOut(true);
    setError(null);

    try {
      await apiRequest<void>("/api/auth/logout", { method: "POST" });
      router.replace("/login");
      router.refresh();
    } catch (requestError) {
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "Unable to log out. Please try again.",
      );
      setIsLoggingOut(false);
    }
  }

  const displayName = user?.display_name || "No display name set";
  const email = user?.email || "Loading account…";

  return (
    <PageShell>
      <PageHeader
        backHref={backHref}
        backLabel={backLabel}
        description="Manage the personal details and security connected to your Cortex account."
        eyebrow="Account"
        headingId="account-settings-title"
        title="Your settings"
      />

      <FeedbackAlert message={error ?? loadError ?? null} />

      <div className="mt-10 space-y-5">
          <SettingsSection
            id="profile"
            title="Profile"
            description="The identity other members see when you collaborate."
          >
            <div className="flex flex-wrap items-center gap-4 px-6 py-5">
              <span className="grid size-12 shrink-0 place-items-center rounded-full border border-border/35 bg-surface-raised font-mono text-sm font-semibold text-foreground">
                {accountInitials(user)}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-base font-medium text-foreground">
                  {displayName}
                </p>
                <p className="mt-0.5 truncate text-sm text-muted">{email}</p>
              </div>
              <UnavailableAction>Edit profile</UnavailableAction>
            </div>
            <div className="grid gap-5 border-t border-border/20 px-6 py-5 sm:grid-cols-2">
              <SettingsValue label="Display name" value={displayName} />
              <SettingsValue label="Email address" value={email} />
            </div>
            <p className="border-t border-border/20 px-6 py-3 text-xs text-subtle">
              Profile editing will be enabled when account updates are connected.
            </p>
          </SettingsSection>

          <SettingsSection
            id="security"
            title="Security"
            description="Control access to your account and active session."
          >
            <div className="divide-y divide-border/20">
              <SettingsRow
                title="Password"
                description="Change the password used to sign in to Cortex."
                action={<UnavailableAction>Change password</UnavailableAction>}
              />
              <SettingsRow
                title="Current session"
                description="Sign out of Cortex on this device."
                action={
                  <Button
                    type="button"
                    onClick={logout}
                    disabled={isLoggingOut}
                    size="small"
                    variant="muted"
                    className="disabled:cursor-wait"
                  >
                    {isLoggingOut ? "Signing out…" : "Sign out"}
                  </Button>
                }
              />
            </div>
          </SettingsSection>

          <SettingsSection
            id="delete-account"
            title="Delete account"
            description="Permanently remove your account and personal data."
            danger
          >
            <div className="flex items-center justify-between gap-5 px-6 py-5">
              <p className="max-w-2xl text-sm leading-6 text-muted">
                This action cannot be undone. Workspace deletion and ownership transfer
                will be handled before this becomes available.
              </p>
              <UnavailableAction danger>Delete account</UnavailableAction>
            </div>
          </SettingsSection>
      </div>
    </PageShell>
  );
}
