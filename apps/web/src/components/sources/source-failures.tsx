"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, buttonClassName } from "@/components/ui/button";
import { FeedbackAlert } from "@/components/ui/feedback-alert";
import { ApiError, apiRequest } from "@/lib/api";
import type { IngestResult, SourceFailure } from "@/lib/api-types";
import { formatAbsoluteTime, formatRelativeTime } from "@/lib/relative-time";
import { routes } from "@/lib/routes";

/**
 * T-12.2: reviewing a broken source and fixing it.
 *
 * Two exports, one fact. `SourceFailureBanner` sits in the workspace shell so a
 * failure is noticed from any page (AC1); `SourceFailureList` is the Sources
 * page's full account, with the actions. They share `useSourceFailures`, so the
 * banner can never claim a count the list contradicts.
 *
 * The actions come from the server's `needs_reauth` / `can_retry`, never from
 * the category: which failures a sign-in can fix is a fact about the GitHub
 * integration, and re-deriving it here would be a second place to keep right.
 */

/** Where the GitHub sign-in starts. A plain link, not a fetch: the endpoint
 *  answers with a redirect to GitHub and the browser has to follow it. */
const GITHUB_SIGN_IN = "/api/auth/github/login";

function githubUrl(repo: string) {
  return `https://github.com/${repo.split("/").map(encodeURIComponent).join("/")}`;
}

function WarningIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className="size-5">
      <path d="M10.3 3.9 2.4 17.5a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
      <path d="M12 9v4M12 17h.01" />
    </svg>
  );
}

function failureSummary(count: number) {
  return count === 1 ? "1 source needs attention" : `${count} sources need attention`;
}

/**
 * The workspace-wide notice (AC1).
 *
 * A strip above the page rather than a toast: a stale graph is a standing
 * condition, not an event, and it should still be on screen when the reader
 * finally looks up from whatever they were doing.
 */
export function SourceFailureBanner({
  workspaceId,
  failures,
}: {
  workspaceId: string;
  failures: SourceFailure[];
}) {
  if (failures.length === 0) return null;

  const [first] = failures;

  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-4 gap-y-2 border-b border-red-400/20 bg-red-400/[0.07] px-[var(--cortex-page-gutter)] py-3"
    >
      <span aria-hidden="true" className="text-red-300">
        <WarningIcon />
      </span>
      <p className="min-w-0 flex-1 text-sm text-red-200">
        <span className="font-semibold">{failureSummary(failures.length)}.</span>{" "}
        <span className="text-red-200/80">
          {failures.length === 1
            ? `${first.repo}: ${first.label.toLowerCase()}.`
            : "Cortex could not read them, so the graph may be out of date."}
        </span>
      </p>
      <Link
        href={routes.workspace.sources(workspaceId)}
        className={buttonClassName({ size: "small", variant: "muted" })}
      >
        Review sources
      </Link>
    </div>
  );
}

function FailureRow({
  workspaceId,
  failure,
  onFixed,
  disabled,
  onBusyChange,
}: {
  workspaceId: string;
  failure: SourceFailure;
  onFixed: () => void;
  disabled: boolean;
  onBusyChange: (repo: string | null) => void;
}) {
  const router = useRouter();
  const [retrying, setRetrying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Re-ingest the source. The same `POST /api/ingest/github` the Sources page
   * sends, because "fix it and sync again" is an ordinary ingestion -- there is
   * no separate repair path, and inventing one would be a second code path for
   * the thing that already failed once.
   */
  async function retry() {
    setRetrying(true);
    onBusyChange(failure.repo);
    setError(null);
    try {
      await apiRequest<IngestResult>("/api/ingest/github", {
        method: "POST",
        body: JSON.stringify({
          repo_url: githubUrl(failure.repo),
          workspace_id: workspaceId,
        }),
      });
    } catch (requestError) {
      if (requestError instanceof ApiError && requestError.status === 401) {
        router.replace("/login");
        return;
      }
      // The server records its own failures against the source, so a second
      // failure arrives as a refreshed row. This covers what never reached it.
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : `Could not reach Cortex to re-sync ${failure.repo}.`,
      );
    } finally {
      setRetrying(false);
      onBusyChange(null);
      // Either way: the row has either gone or changed its reason.
      onFixed();
    }
  }

  const staleness = formatRelativeTime(failure.last_synced_at);

  return (
    <li className="py-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-md border border-red-400/25 bg-red-400/10 px-2 py-1 font-mono text-[0.625rem] font-semibold uppercase tracking-[0.1em] text-red-300">
              {failure.label}
            </span>
            <a
              href={githubUrl(failure.repo)}
              target="_blank"
              rel="noreferrer"
              className="truncate font-medium text-foreground transition-colors hover:text-accent-bright"
            >
              {failure.repo}
              <span className="sr-only"> (opens on GitHub)</span>
            </a>
          </div>

          {failure.message ? (
            <p className="mt-2 max-w-prose text-sm leading-6 text-red-300/80">
              {failure.message}
            </p>
          ) : null}
          <p className="mt-1.5 max-w-prose text-sm leading-6 text-muted">
            {failure.advice}
          </p>

          {/*
            AC4: a source can be failing now and still be showing data from a
            sync that worked. Saying how old it is, is the difference between a
            graph the reader can still use and one they cannot trust.
          */}
          <p className="mt-2 text-xs text-subtle">
            {staleness ? (
              <span title={formatAbsoluteTime(failure.last_synced_at)}>
                Showing data from {staleness}
                {failure.last_synced_by_name ? `, synced by ${failure.last_synced_by_name}` : ""}
              </span>
            ) : (
              "Never synced successfully, so nothing from this source is indexed"
            )}
            {failure.last_attempted_at ? (
              <>
                {" · "}
                <span title={formatAbsoluteTime(failure.last_attempted_at)}>
                  last tried {formatRelativeTime(failure.last_attempted_at)}
                </span>
              </>
            ) : null}
          </p>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {/* AC2: an authorization failure offers the sign-in flow. */}
          {failure.needs_reauth ? (
            <a
              href={GITHUB_SIGN_IN}
              className={buttonClassName({ size: "small", variant: "primary" })}
            >
              Reconnect GitHub
            </a>
          ) : null}
          {failure.can_retry ? (
            <Button
              type="button"
              size="small"
              variant="muted"
              onClick={() => void retry()}
              disabled={disabled || retrying}
              aria-label={`Try ${failure.repo} again`}
            >
              {retrying ? "Syncing…" : "Try again"}
            </Button>
          ) : null}
        </div>
      </div>
      <FeedbackAlert message={error} />
    </li>
  );
}

/** The Sources page's account of what is broken, with the fixes. */
export function SourceFailureList({
  workspaceId,
  failures,
  onChanged,
}: {
  workspaceId: string;
  failures: SourceFailure[];
  /** Called after a retry, so the source list reloads alongside. */
  onChanged: () => void;
}) {
  // One ingestion at a time: it is heavy and shares the workspace's GitHub rate
  // limit, so a retry anywhere disables every other retry.
  const [busyRepo, setBusyRepo] = useState<string | null>(null);

  if (failures.length === 0) return null;

  return (
    <section aria-labelledby="source-failures-heading" className="mt-12">
      <div className="border-b border-red-400/20 pb-4">
        <h2
          id="source-failures-heading"
          className="flex items-center gap-2 text-base font-semibold text-foreground"
        >
          <span aria-hidden="true" className="text-red-300">
            <WarningIcon />
          </span>
          Needs attention
        </h2>
        <p className="mt-1 text-sm text-muted">
          {failureSummary(failures.length)}. Until each is fixed, the graph is
          missing whatever changed in it since the last successful sync.
        </p>
      </div>

      <ul className="divide-y divide-border/20">
        {failures.map((failure) => (
          <FailureRow
            key={`${failure.kind}:${failure.repo}`}
            workspaceId={workspaceId}
            failure={failure}
            onFixed={onChanged}
            disabled={busyRepo !== null && busyRepo !== failure.repo}
            onBusyChange={setBusyRepo}
          />
        ))}
      </ul>
    </section>
  );
}
