"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { AuthenticatedUser } from "@/lib/api-types";

type GitHubCallbackProps = {
  code: string | null;
  state: string | null;
  // Set by GitHub when the user declines access or the app is misconfigured.
  error: string | null;
};

/**
 * Landing page for GitHub's redirect. Relays code + state to the backend, which
 * checks the state against its cookie, exchanges the code, and opens a session.
 */
export function GitHubCallback({ code, state, error }: GitHubCallbackProps) {
  const router = useRouter();
  const initialError =
    error === "access_denied"
      ? "GitHub sign-in was cancelled."
      : error || !code || !state
        ? "GitHub sign-in failed. Please try again."
        : null;
  const [failure, setFailure] = useState<string | null>(initialError);
  // A code is single-use: StrictMode's second effect run must not resend it.
  const sent = useRef(false);

  useEffect(() => {
    if (initialError || sent.current) return;
    sent.current = true;

    apiRequest<AuthenticatedUser>("/api/auth/github/callback", {
      method: "POST",
      body: JSON.stringify({ code, state }),
    })
      .then(() => {
        router.replace("/workspaces");
        router.refresh();
      })
      .catch((requestError: unknown) => {
        setFailure(
          requestError instanceof ApiError
            ? requestError.message
            : "Unable to reach Cortex. Please try again.",
        );
      });
  }, [code, state, initialError, router]);

  return (
    <section aria-labelledby="github-callback-heading" className="w-full max-w-[28rem]">
      <h1
        id="github-callback-heading"
        className="text-[clamp(2.25rem,4vw,2.75rem)] font-semibold leading-[1.05] tracking-[-0.05em] text-foreground"
      >
        {failure ? "Sign-in failed" : "Signing you in…"}
      </h1>
      {failure ? (
        <>
          <FeedbackAlert message={failure} />
          <Link
            href="/login"
            className="mt-7 inline-block text-sm font-semibold text-accent-bright transition-colors hover:text-foreground"
          >
            Back to log in
          </Link>
        </>
      ) : (
        <p role="status" className="mt-3 text-base leading-7 text-muted">
          Confirming your GitHub account.
        </p>
      )}
    </section>
  );
}
