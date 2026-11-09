"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { ChatConnection, ChatKind } from "@/lib/api-types";
import { routes } from "@/lib/routes";
import { CHAT_KIND_LABELS } from "@/lib/source-kinds";

type ChatInstallCallbackProps = {
  provider: ChatKind;
  code: string | null;
  state: string | null;
  /** Set by the provider when the user declines, or the app is misconfigured. */
  error: string | null;
};

/**
 * T-8.2: landing page for Slack's and Discord's redirect.
 *
 * Relays code + state to the backend, which checks the state against its
 * cookie, re-checks the caller's permission, exchanges the code and stores the
 * connection. The page itself never learns which workspace it is for -- only
 * the server-side transaction knows that -- so the redirect target comes back
 * in the response.
 */
export function ChatInstallCallback({
  provider,
  code,
  state,
  error,
}: ChatInstallCallbackProps) {
  const router = useRouter();
  const label = CHAT_KIND_LABELS[provider];
  const initialError =
    error === "access_denied"
      ? `Connecting ${label} was cancelled.`
      : error || !code || !state
        ? `Connecting ${label} failed. Please try again.`
        : null;
  const [failure, setFailure] = useState<string | null>(initialError);
  // A code is single-use: StrictMode's second effect run must not resend it.
  const sent = useRef(false);

  useEffect(() => {
    if (initialError || sent.current) return;
    sent.current = true;

    apiRequest<ChatConnection & { workspace_id: string }>(
      `/api/sources/${provider}/callback`,
      { method: "POST", body: JSON.stringify({ code, state }) },
    )
      .then((connection) => {
        router.replace(routes.workspace.sources(connection.workspace_id));
        router.refresh();
      })
      .catch((requestError: unknown) => {
        setFailure(
          requestError instanceof ApiError
            ? requestError.message
            : "Unable to reach Cortex. Please try again.",
        );
      });
  }, [code, initialError, provider, router, state]);

  return (
    <section
      aria-labelledby="chat-install-heading"
      className="w-full max-w-[28rem]"
    >
      <h1
        id="chat-install-heading"
        className="text-[clamp(2.25rem,4vw,2.75rem)] font-semibold leading-[1.05] tracking-[-0.05em] text-foreground"
      >
        {failure ? `${label} not connected` : `Connecting ${label}…`}
      </h1>
      {failure ? (
        <>
          <FeedbackAlert message={failure} />
          <Link
            href={routes.workspaces}
            className="mt-7 inline-block text-sm font-semibold text-accent-bright transition-colors hover:text-foreground"
          >
            Back to your workspaces
          </Link>
        </>
      ) : (
        <p role="status" className="mt-3 text-base leading-7 text-muted">
          Saving the connection to your workspace.
        </p>
      )}
    </section>
  );
}
