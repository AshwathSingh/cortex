"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ReactNode } from "react";

import { FeedbackAlert } from "@/components/ui/feedback-alert";
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

function SettingsSection({
  title,
  description,
  children,
  danger = false,
}: {
  title: string;
  description: string;
  children: ReactNode;
  danger?: boolean;
}) {
  const titleId = `${title.toLowerCase().replaceAll(" ", "-")}-title`;

  return (
    <section
      aria-labelledby={titleId}
      className={`overflow-hidden rounded-2xl border bg-surface/55 ${
        danger ? "border-red-400/20" : "border-border/30"
      }`}
    >
      <div className="border-b border-border/20 px-6 py-5">
        <h2
          id={titleId}
          className="text-base font-semibold tracking-[-0.015em] text-foreground"
        >
          {title}
        </h2>
        <p className="mt-1 text-sm leading-6 text-muted">{description}</p>
      </div>
      {children}
    </section>
  );
}

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[0.6875rem] font-semibold uppercase tracking-[0.12em] text-subtle">
        {label}
      </p>
      <p className="mt-1.5 truncate text-sm text-foreground">{value}</p>
    </div>
  );
}

const unavailableActionClass =
  "min-h-9 shrink-0 cursor-not-allowed rounded-lg border border-border/30 px-3 text-xs font-semibold text-subtle opacity-60";

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
    <main className="min-h-screen px-[var(--cortex-page-gutter)] py-8 sm:py-12">
      <div className="mx-auto w-full max-w-[64rem]">
        {backHref && backLabel ? (
          <Link
            href={backHref}
            className="text-sm font-medium text-muted transition-colors hover:text-foreground"
          >
            ← {backLabel}
          </Link>
        ) : null}

        <header className={backHref ? "mt-10" : undefined}>
          <p className="text-sm font-medium text-accent-bright">Account</p>
          <h1 className="mt-3 text-[clamp(2.25rem,6vw,4rem)] font-semibold leading-none tracking-[-0.05em]">
            Your settings
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-7 text-muted">
            Manage the personal details and security connected to your Cortex account.
          </p>
        </header>

        <FeedbackAlert message={error ?? loadError ?? null} />

        <div className="mt-10 space-y-5">
          <SettingsSection
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
              <button type="button" disabled className={unavailableActionClass}>
                Edit profile
              </button>
            </div>
            <div className="grid gap-5 border-t border-border/20 px-6 py-5 sm:grid-cols-2">
              <ReadOnlyField label="Display name" value={displayName} />
              <ReadOnlyField label="Email address" value={email} />
            </div>
            <p className="border-t border-border/20 px-6 py-3 text-xs text-subtle">
              Profile editing will be enabled when account updates are connected.
            </p>
          </SettingsSection>

          <SettingsSection
            title="Security"
            description="Control access to your account and active session."
          >
            <div className="flex items-center justify-between gap-5 px-6 py-5">
              <div>
                <h3 className="text-sm font-medium text-foreground">Password</h3>
                <p className="mt-1 text-sm leading-6 text-muted">
                  Change the password used to sign in to Cortex.
                </p>
              </div>
              <button type="button" disabled className={unavailableActionClass}>
                Change password
              </button>
            </div>
            <div className="flex items-center justify-between gap-5 border-t border-border/20 px-6 py-5">
              <div>
                <h3 className="text-sm font-medium text-foreground">Current session</h3>
                <p className="mt-1 text-sm leading-6 text-muted">
                  Sign out of Cortex on this device.
                </p>
              </div>
              <button
                type="button"
                onClick={logout}
                disabled={isLoggingOut}
                className="min-h-9 shrink-0 rounded-lg border border-border/40 px-3 text-xs font-semibold text-muted transition-colors hover:border-border hover:bg-surface-raised hover:text-foreground disabled:cursor-wait disabled:opacity-60"
              >
                {isLoggingOut ? "Signing out…" : "Sign out"}
              </button>
            </div>
          </SettingsSection>

          <SettingsSection
            title="Delete account"
            description="Permanently remove your account and personal data."
            danger
          >
            <div className="flex items-center justify-between gap-5 px-6 py-5">
              <p className="max-w-2xl text-sm leading-6 text-muted">
                This action cannot be undone. Workspace deletion and ownership transfer
                will be handled before this becomes available.
              </p>
              <button
                type="button"
                disabled
                className="min-h-9 shrink-0 cursor-not-allowed rounded-lg border border-red-400/25 px-3 text-xs font-semibold text-red-300/60"
              >
                Delete account
              </button>
            </div>
          </SettingsSection>
        </div>
      </div>
    </main>
  );
}
