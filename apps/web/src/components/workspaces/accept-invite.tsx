"use client";

import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";

import { Button, buttonClassName } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { RoleBadge } from "@/components/workspaces/role-badge";
import { ApiError, apiRequest } from "@/lib/api";
import type {
  AuthenticatedUser,
  WorkspaceInviteAcceptance,
} from "@/lib/api-types";
import { acceptWorkspaceInvite } from "@/lib/invite-client";
import {
  capturePendingInviteToken,
  clearPendingInviteToken,
} from "@/lib/invite-link";
import { routes } from "@/lib/routes";

type AuthStatus = "checking" | "signed-in" | "signed-out" | "failed";

export function AcceptInvite() {
  const [token, setToken] = useState<string | null>();
  const [authStatus, setAuthStatus] = useState<AuthStatus>("checking");
  const [user, setUser] = useState<AuthenticatedUser | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authAttempt, setAuthAttempt] = useState(0);
  const [isAccepting, setIsAccepting] = useState(false);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [accepted, setAccepted] =
    useState<WorkspaceInviteAcceptance | null>(null);

  useEffect(() => {
    const timeout = window.setTimeout(() => {
      setToken(capturePendingInviteToken());
    }, 0);
    return () => window.clearTimeout(timeout);
  }, []);

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();

    apiRequest<AuthenticatedUser>("/api/auth/me", {
      signal: controller.signal,
    })
      .then((currentUser) => {
        setUser(currentUser);
        setAuthStatus("signed-in");
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (error instanceof ApiError && error.status === 401) {
          setAuthStatus("signed-out");
          return;
        }
        setAuthError("Unable to check your Cortex session.");
        setAuthStatus("failed");
      });

    return () => controller.abort();
  }, [authAttempt, token]);

  function retryAuthentication() {
    setAuthError(null);
    setAuthStatus("checking");
    setAuthAttempt((attempt) => attempt + 1);
  }

  async function acceptInvitation() {
    if (!token) return;
    setAcceptError(null);
    setIsAccepting(true);
    try {
      const result = await acceptWorkspaceInvite(token);
      clearPendingInviteToken();
      setAccepted(result);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        setAuthStatus("signed-out");
        return;
      }
      setAcceptError(
        error instanceof ApiError
          ? error.message
          : "Unable to accept this invitation.",
      );
    } finally {
      setIsAccepting(false);
    }
  }

  if (token === undefined) {
    return <InviteStatus message="Opening your invitation…" />;
  }

  if (!token) {
    return (
      <InviteCard
        title="Invitation link missing"
        description="Open the complete invitation link that a workspace member shared with you."
      >
        <FeedbackAlert message="This link does not contain an invitation token." />
        <Link
          href="/"
          className={buttonClassName({ className: "mt-6", variant: "primary" })}
        >
          Go to Cortex
        </Link>
      </InviteCard>
    );
  }

  if (accepted) {
    return (
      <InviteCard
        title="You joined the workspace"
        description="Your new workspace is ready to open."
      >
        <div className="mt-6 flex items-center justify-between rounded-control border border-accent-bright/25 bg-accent/10 px-4 py-3">
          <span className="text-sm text-muted">Your access</span>
          <RoleBadge role={accepted.role} />
        </div>
        <Link
          href={routes.workspace.home(accepted.workspace_id)}
          className={buttonClassName({
            className: "mt-6 w-full",
            size: "large",
            variant: "primary",
          })}
        >
          Open workspace
        </Link>
      </InviteCard>
    );
  }

  if (authStatus === "checking") {
    return <InviteStatus message="Checking your Cortex account…" />;
  }

  if (authStatus === "failed") {
    return (
      <InviteCard
        title="We could not check your account"
        description="Your invitation is still saved in this browser."
      >
        <FeedbackAlert message={authError} />
        <Button
          type="button"
          variant="primary"
          className="mt-6"
          onClick={retryAuthentication}
        >
          Try again
        </Button>
      </InviteCard>
    );
  }

  if (authStatus === "signed-out") {
    return (
      <InviteCard
        title="Join a Cortex workspace"
        description="Log in or create an account. Your invitation will be waiting when you return."
      >
        <div className="mt-7 grid gap-3 sm:grid-cols-2">
          <Link
            href="/login"
            className={buttonClassName({ size: "large", variant: "primary" })}
          >
            Log in to accept
          </Link>
          <Link
            href="/signup"
            className={buttonClassName({ size: "large" })}
          >
            Create account
          </Link>
        </div>
        <Link
          href="/"
          onClick={clearPendingInviteToken}
          className="mt-5 block text-center text-sm font-semibold text-muted transition-colors hover:text-foreground"
        >
          Not now
        </Link>
      </InviteCard>
    );
  }

  return (
    <InviteCard
      title="Accept workspace invitation"
      description="Only continue if this private invitation was shared directly with you."
    >
      <div className="mt-6 rounded-control border border-border/30 bg-background/35 px-4 py-3">
        <p className="text-xs font-semibold uppercase tracking-[0.1em] text-subtle">
          Signed in as
        </p>
        <p className="mt-1 text-sm text-foreground">
          {user?.display_name || user?.email}
        </p>
        {user?.display_name ? (
          <p className="mt-0.5 text-xs text-muted">{user.email}</p>
        ) : null}
      </div>
      <FeedbackAlert message={acceptError} />
      <Button
        type="button"
        size="large"
        variant="primary"
        className="mt-6 w-full"
        disabled={isAccepting}
        onClick={acceptInvitation}
      >
        {isAccepting ? "Joining workspace…" : "Accept invitation"}
      </Button>
      <Link
        href={routes.workspaces}
        onClick={clearPendingInviteToken}
        className="mt-5 block text-center text-sm font-semibold text-muted transition-colors hover:text-foreground"
      >
        Not now
      </Link>
    </InviteCard>
  );
}

function InviteStatus({ message }: { message: string }) {
  return (
    <InviteCard title="Workspace invitation" description={message}>
      <p role="status" className="mt-6 text-sm text-muted">
        Please wait…
      </p>
    </InviteCard>
  );
}

function InviteCard({
  children,
  description,
  title,
}: {
  children: ReactNode;
  description: string;
  title: string;
}) {
  return (
    <section
      aria-labelledby="invite-accept-title"
      className="w-full max-w-[28rem]"
    >
      <p className="text-sm font-medium text-accent-bright">Workspace invite</p>
      <h1
        id="invite-accept-title"
        className="mt-3 text-[clamp(2.25rem,4vw,2.75rem)] font-semibold leading-[1.05] tracking-[-0.05em] text-foreground"
      >
        {title}
      </h1>
      <p className="mt-3 text-base leading-7 text-muted">{description}</p>
      {children}
    </section>
  );
}
